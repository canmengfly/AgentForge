"""ClickHouse connector — fetches rows via HTTP interface (clickhouse-connect)."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..document_processor import ParsedDocument, _make_id


@dataclass
class ClickHouseConfig:
    host: str
    database: str
    username: str = "default"
    password: str = ""
    port: int = 8123
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000
    secure: bool = False


class ClickHouseConnector:
    def __init__(self, config: ClickHouseConfig):
        self.config = config

    def _make_client(self):
        try:
            import clickhouse_connect
        except ImportError as e:
            raise RuntimeError("clickhouse-connect required: pip install clickhouse-connect") from e
        return clickhouse_connect.get_client(
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
            username=self.config.username,
            password=self.config.password,
            secure=self.config.secure,
        )

    def _test_sync(self) -> dict:
        try:
            client = self._make_client()
            client.query("SELECT 1")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _list_tables(self, client) -> list[str]:
        if self.config.tables:
            return self.config.tables
        result = client.query(
            "SELECT name FROM system.tables WHERE database = {db:String}",
            parameters={"db": self.config.database},
        )
        return [row[0] for row in result.result_rows]

    def _collect(self, since_ts: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        client = self._make_client()
        docs: list[ParsedDocument] = []
        tables = self._list_tables(client)
        max_ts = time.time()

        for table in tables:
            try:
                result = client.query(
                    f"SELECT * FROM {self.config.database}.`{table}` LIMIT {self.config.row_limit}"
                )
                columns = result.column_names
                for row in result.result_rows:
                    record = dict(zip(columns, row))
                    doc = self._row_to_doc(record, table)
                    if doc:
                        docs.append(doc)
            except Exception:
                continue

        cursor = {"last_ts": max_ts}
        return docs, cursor

    def _row_to_doc(self, record: dict, table: str) -> ParsedDocument | None:
        parts = [f"{k}: {v}" for k, v in record.items() if v is not None]
        content = "\n".join(parts)
        if not content.strip():
            return None

        row_key = str(record.get("id") or record.get("_id") or hash(content))
        doc_key = f"clickhouse:{self.config.database}:{table}:{row_key}"
        title = str(record.get("title") or record.get("name") or f"{table}/{row_key}")
        doc = ParsedDocument(
            doc_id=_make_id(doc_key),
            title=title,
            source=f"clickhouse://{self.config.host}/{self.config.database}/{table}",
            content=content,
            metadata={
                "source_type": "clickhouse",
                "ch_database": self.config.database,
                "ch_table": table,
            },
        )
        return doc

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, 0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        # ClickHouse is append-optimized; fall back to full sync for simplicity
        return await self.sync_documents()
