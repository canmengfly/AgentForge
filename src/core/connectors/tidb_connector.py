"""TiDB connector — MySQL-wire protocol, default port 4000."""
from __future__ import annotations

from dataclasses import dataclass, field

from .sql_connector import SQLConnector, SQLConfig
from ..document_processor import ParsedDocument


@dataclass
class TiDBConfig:
    host: str
    database: str
    username: str
    password: str
    port: int = 4000
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000
    watermark_col: str = ""


class TiDBConnector:
    def __init__(self, config: TiDBConfig):
        self._inner = SQLConnector(SQLConfig(
            driver="mysql",
            host=config.host,
            port=config.port,
            database=config.database,
            username=config.username,
            password=config.password,
            tables=config.tables,
            row_limit=config.row_limit,
            watermark_col=config.watermark_col,
        ))

    async def test_connection(self) -> dict:
        return await self._inner.test_connection()

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        docs, cursor = await self._inner.sync_documents()
        for doc in docs:
            doc.metadata["source_type"] = "tidb"
        return docs, cursor

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        docs, new_cursor = await self._inner.sync_incremental(cursor)
        for doc in docs:
            doc.metadata["source_type"] = "tidb"
        return docs, new_cursor
