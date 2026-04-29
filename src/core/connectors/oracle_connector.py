"""Oracle Database connector — uses oracledb (thin mode, no Oracle Client needed)."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..document_processor import ParsedDocument, _make_id


@dataclass
class OracleConfig:
    host: str
    service_name: str          # Oracle service name (preferred over SID)
    username: str
    password: str
    port: int = 1521
    sid: str = ""              # alternative to service_name
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000


class OracleConnector:
    def __init__(self, config: OracleConfig):
        self.config = config

    def _make_connection(self):
        try:
            import oracledb
        except ImportError as e:
            raise RuntimeError("oracledb required: pip install oracledb") from e
        dsn = (
            f"{self.config.host}:{self.config.port}/{self.config.service_name}"
            if self.config.service_name
            else f"{self.config.host}:{self.config.port}:{self.config.sid}"
        )
        return oracledb.connect(
            user=self.config.username,
            password=self.config.password,
            dsn=dsn,
        )

    def _test_sync(self) -> dict:
        try:
            conn = self._make_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM DUAL")
            conn.close()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _list_tables(self, cursor) -> list[str]:
        if self.config.tables:
            return self.config.tables
        cursor.execute(
            "SELECT table_name FROM user_tables ORDER BY table_name"
        )
        return [row[0] for row in cursor.fetchall()]

    def _row_to_doc(self, record: dict, table: str, idx: int) -> ParsedDocument | None:
        data_lines = [f"{k}: {str(v)[:500]}" for k, v in record.items() if v is not None]
        if not data_lines:
            return None
        content = "\n".join([f"[Table: {table}]"] + data_lines)
        pk_val = (
            record.get("ID") or record.get("id")
            or record.get(f"{table}_ID") or str(idx)
        )
        doc_key = f"oracle:{self.config.host}:{self.config.service_name}:{table}:{pk_val}"
        return ParsedDocument(
            doc_id=_make_id(doc_key),
            title=f"{table} · row {idx + 1}",
            source=f"oracle://{self.config.host}/{self.config.service_name}/{table}",
            content=content,
            metadata={"source_type": "oracle", "table": table, "database": self.config.service_name},
        )

    def _collect(self) -> tuple[list[ParsedDocument], dict]:
        conn = self._make_connection()
        cur = conn.cursor()
        docs: list[ParsedDocument] = []
        try:
            tables = self._list_tables(cur)
            for table in tables:
                try:
                    cur.execute(f'SELECT * FROM "{table}" FETCH FIRST :lim ROWS ONLY',
                                {"lim": self.config.row_limit})
                    cols = [d[0] for d in cur.description]
                    for idx, row in enumerate(cur.fetchall()):
                        record = dict(zip(cols, row))
                        doc = self._row_to_doc(record, table, idx)
                        if doc:
                            docs.append(doc)
                except Exception:
                    continue
        finally:
            conn.close()
        return docs, {"last_ts": time.time()}

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self.sync_documents()
