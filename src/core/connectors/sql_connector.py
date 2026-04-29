"""MySQL / PostgreSQL connector — indexes table rows as searchable documents."""
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from ..document_processor import ParsedDocument, _make_id

_IDENT_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]{0,63}$')

# Common primary-key column name patterns (checked in order)
_PK_CANDIDATES = ("id", "pk", "uuid", "guid", "key")


def _row_stable_key(table: str, row: dict) -> str:
    """Return a stable string that identifies this row, preferring a PK column."""
    t_lower = table.lower()
    # Also try singular form: "orders" → "order"
    t_singular = t_lower[:-1] if t_lower.endswith("s") and len(t_lower) > 2 else t_lower
    pk_names = set(_PK_CANDIDATES) | {
        f"{t_lower}_id", f"{t_lower}id",
        f"{t_singular}_id", f"{t_singular}id",
    }
    for k, v in row.items():
        if k.lower() in pk_names and v is not None:
            return f"pk:{k}:{v}"
    # Fallback: hash the full row content (stable for identical rows)
    content_sig = str(sorted((k, str(v)[:200]) for k, v in row.items()))
    import hashlib
    return "content:" + hashlib.md5(content_sig.encode()).hexdigest()


@dataclass
class SQLConfig:
    driver: Literal["mysql", "postgres"]
    host: str
    port: int
    database: str
    username: str
    password: str
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000
    watermark_col: str = ""   # optional column for incremental sync (e.g. "id" or "created_at")


def _validate_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def _quote(name: str, driver: str) -> str:
    return f"`{name}`" if driver == "mysql" else f'"{name}"'


def _row_to_text(table: str, row: dict) -> str:
    lines = [f"[Table: {table}]"]
    for k, v in row.items():
        if v is None:
            continue
        lines.append(f"{k}: {str(v)[:500]}")
    return "\n".join(lines)


def _make_doc(table: str, row: dict, config: "SQLConfig", row_idx: int) -> ParsedDocument:
    content = _row_to_text(table, row)
    stable_key = _row_stable_key(table, row)
    doc_id = _make_id(f"sql:{config.host}:{config.database}:{table}:{stable_key}")
    return ParsedDocument(
        doc_id=doc_id,
        title=f"{table} · row {row_idx + 1}",
        source=f"sql://{config.host}/{config.database}/{table}",
        content=content,
        metadata={
            "table": table,
            "row_index": row_idx,
            "database": config.database,
            "driver": config.driver,
            "source_type": "sql",
        },
    )


class SQLConnector:
    def __init__(self, config: SQLConfig):
        self.config = config

    def _make_engine(self):
        try:
            from sqlalchemy import create_engine
        except ImportError as e:
            raise RuntimeError("sqlalchemy required: pip install sqlalchemy") from e

        if self.config.driver == "mysql":
            try:
                import pymysql  # noqa: F401
            except ImportError as e:
                raise RuntimeError("PyMySQL required: pip install PyMySQL") from e
            url = (
                f"mysql+pymysql://{self.config.username}:{self.config.password}"
                f"@{self.config.host}:{self.config.port}/{self.config.database}"
                "?charset=utf8mb4"
            )
        else:
            try:
                import psycopg2  # noqa: F401
            except ImportError as e:
                raise RuntimeError("psycopg2 required: pip install psycopg2-binary") from e
            url = (
                f"postgresql+psycopg2://{self.config.username}:{self.config.password}"
                f"@{self.config.host}:{self.config.port}/{self.config.database}"
            )
        return create_engine(url, pool_pre_ping=True)

    def _test_sync(self) -> dict:
        try:
            from sqlalchemy import text
            engine = self._make_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    # ── internal sync helpers ────────────────────────────────────────────────

    def _get_tables(self, engine) -> list[str]:
        from sqlalchemy import inspect
        inspector = inspect(engine)
        targets = self.config.tables if self.config.tables else inspector.get_table_names()
        validated = []
        for t in targets:
            try:
                validated.append(_validate_ident(t))
            except ValueError:
                continue
        return validated

    def _full_sync(self) -> tuple[list[ParsedDocument], dict]:
        from sqlalchemy import inspect, text
        engine = self._make_engine()
        tables = self._get_tables(engine)
        docs: list[ParsedDocument] = []
        last_vals: dict[str, str] = {}

        with engine.connect() as conn:
            for table in tables:
                q = _quote(table, self.config.driver)
                try:
                    result = conn.execute(
                        text(f"SELECT * FROM {q} LIMIT :lim"),
                        {"lim": self.config.row_limit},
                    )
                    rows = result.mappings().all()
                    for i, row in enumerate(rows):
                        docs.append(_make_doc(table, dict(row), self.config, i))
                    # Track watermark max for cursor
                    if self.config.watermark_col and rows:
                        wc = _validate_ident(self.config.watermark_col)
                        wq = _quote(wc, self.config.driver)
                        r = conn.execute(text(f"SELECT MAX({wq}) FROM {q}"))
                        val = r.scalar()
                        if val is not None:
                            last_vals[table] = str(val)
                except Exception:
                    continue

        engine.dispose()
        cursor: dict = {}
        if self.config.watermark_col and last_vals:
            # Use the max across all tables as the global watermark
            cursor = {"col": self.config.watermark_col, "last_val": max(last_vals.values())}
        return docs, cursor

    def _incremental_sync(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        """Return only rows with watermark_col > cursor['last_val'].

        Falls back to full sync if no watermark is configured.
        """
        wc_name = cursor.get("col") or self.config.watermark_col
        last_val = cursor.get("last_val")

        if not wc_name or last_val is None:
            # No watermark available — fall back to full resync
            return self._full_sync()

        try:
            wc = _validate_ident(wc_name)
        except ValueError:
            return self._full_sync()

        from sqlalchemy import text
        engine = self._make_engine()
        tables = self._get_tables(engine)
        docs: list[ParsedDocument] = []
        new_max = last_val

        with engine.connect() as conn:
            for table in tables:
                q = _quote(table, self.config.driver)
                wq = _quote(wc, self.config.driver)
                try:
                    result = conn.execute(
                        text(
                            f"SELECT * FROM {q} WHERE {wq} > :last_val"
                            f" ORDER BY {wq} LIMIT :lim"
                        ),
                        {"last_val": last_val, "lim": self.config.row_limit},
                    )
                    rows = result.mappings().all()
                    base = 0
                    for i, row in enumerate(rows):
                        docs.append(_make_doc(table, dict(row), self.config, base + i))
                    if rows:
                        last_row_val = str(rows[-1][wc])
                        if last_row_val > new_max:
                            new_max = last_row_val
                except Exception:
                    continue

        engine.dispose()
        new_cursor = {"col": wc, "last_val": new_max}
        return docs, new_cursor

    # ── public async interface ───────────────────────────────────────────────

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        """Full sync — returns (all_docs, cursor)."""
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._full_sync)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        """Incremental sync — returns only new rows since cursor."""
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._incremental_sync, cursor)
