"""Snowflake connector — queries tables via snowflake-sqlalchemy."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..document_processor import ParsedDocument, _make_id


@dataclass
class SnowflakeConfig:
    account: str             # e.g. "myorg-myaccount" or "myaccount.us-east-1"
    user: str
    password: str
    database: str
    schema: str = "PUBLIC"
    warehouse: str = ""
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000


class SnowflakeConnector:
    def __init__(self, config: SnowflakeConfig):
        self.config = config

    def _make_engine(self):
        try:
            from sqlalchemy import create_engine
            import snowflake.sqlalchemy  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "snowflake-sqlalchemy required: pip install snowflake-sqlalchemy"
            ) from e

        url = (
            f"snowflake://{self.config.user}:{self.config.password}"
            f"@{self.config.account}/{self.config.database}/{self.config.schema}"
        )
        connect_args: dict = {}
        if self.config.warehouse:
            connect_args["warehouse"] = self.config.warehouse
        return create_engine(url, connect_args=connect_args)

    def _test_sync(self) -> dict:
        try:
            from sqlalchemy import text
            engine = self._make_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT CURRENT_VERSION()"))
            engine.dispose()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _list_tables(self, engine) -> list[str]:
        if self.config.tables:
            return self.config.tables
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_TYPE = 'BASE TABLE'"),
                {"schema": self.config.schema.upper()},
            )
            return [row[0] for row in result]

    def _row_to_doc(self, record: dict, table: str, idx: int) -> ParsedDocument | None:
        parts = [f"[Table: {table}]"] + [
            f"{k}: {str(v)[:500]}" for k, v in record.items() if v is not None
        ]
        content = "\n".join(parts)
        if not content.strip():
            return None
        pk_val = record.get("ID") or record.get("id") or str(idx)
        doc_key = f"snowflake:{self.config.account}:{self.config.database}:{self.config.schema}:{table}:{pk_val}"
        return ParsedDocument(
            doc_id=_make_id(doc_key),
            title=f"{table} · row {idx + 1}",
            source=f"snowflake://{self.config.account}/{self.config.database}/{self.config.schema}/{table}",
            content=content,
            metadata={
                "source_type": "snowflake",
                "table": table,
                "database": self.config.database,
                "schema": self.config.schema,
            },
        )

    def _collect(self) -> tuple[list[ParsedDocument], dict]:
        from sqlalchemy import text
        engine = self._make_engine()
        tables = self._list_tables(engine)
        docs: list[ParsedDocument] = []

        with engine.connect() as conn:
            for table in tables:
                try:
                    result = conn.execute(
                        text(f'SELECT * FROM "{self.config.schema}"."{table}" LIMIT :lim'),
                        {"lim": self.config.row_limit},
                    )
                    cols = list(result.keys())
                    for idx, row in enumerate(result):
                        record = dict(zip(cols, row))
                        doc = self._row_to_doc(record, table, idx)
                        if doc:
                            docs.append(doc)
                except Exception:
                    continue
        engine.dispose()
        return docs, {"last_ts": time.time()}

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self.sync_documents()
