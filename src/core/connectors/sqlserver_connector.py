"""Microsoft SQL Server connector — uses pymssql."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..document_processor import ParsedDocument, _make_id


@dataclass
class SQLServerConfig:
    host: str
    database: str
    username: str
    password: str
    port: int = 1433
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000
    schema: str = "dbo"


class SQLServerConnector:
    def __init__(self, config: SQLServerConfig):
        self.config = config

    def _make_connection(self):
        try:
            import pymssql
        except ImportError as e:
            raise RuntimeError("pymssql required: pip install pymssql") from e
        return pymssql.connect(
            server=self.config.host,
            port=self.config.port,
            user=self.config.username,
            password=self.config.password,
            database=self.config.database,
            charset="UTF-8",
        )

    def _test_sync(self) -> dict:
        try:
            conn = self._make_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1")
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
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE='BASE TABLE' AND TABLE_SCHEMA=%s",
            (self.config.schema,),
        )
        return [row[0] for row in cursor.fetchall()]

    def _row_to_doc(self, record: dict, table: str, idx: int) -> ParsedDocument | None:
        data_lines = [f"{k}: {str(v)[:500]}" for k, v in record.items() if v is not None]
        if not data_lines:
            return None
        content = "\n".join([f"[Table: {table}]"] + data_lines)
        pk_val = record.get("id") or record.get("ID") or str(idx)
        doc_key = f"sqlserver:{self.config.host}:{self.config.database}:{table}:{pk_val}"
        return ParsedDocument(
            doc_id=_make_id(doc_key),
            title=f"{table} · row {idx + 1}",
            source=f"sqlserver://{self.config.host}/{self.config.database}/{table}",
            content=content,
            metadata={
                "source_type": "sqlserver",
                "table": table,
                "database": self.config.database,
            },
        )

    def _collect(self) -> tuple[list[ParsedDocument], dict]:
        conn = self._make_connection()
        cur = conn.cursor(as_dict=True)
        docs: list[ParsedDocument] = []
        try:
            tables = self._list_tables(cur)
            for table in tables:
                try:
                    cur.execute(
                        f"SELECT TOP {self.config.row_limit} * FROM [{self.config.schema}].[{table}]"
                    )
                    for idx, row in enumerate(cur.fetchall()):
                        doc = self._row_to_doc(dict(row), table, idx)
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
