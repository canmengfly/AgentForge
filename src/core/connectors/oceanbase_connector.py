"""OceanBase connector — MySQL-wire protocol, default port 2881."""
from __future__ import annotations

from dataclasses import dataclass, field

from .sql_connector import SQLConnector, SQLConfig
from ..document_processor import ParsedDocument


@dataclass
class OceanBaseConfig:
    host: str
    database: str
    username: str
    password: str
    port: int = 2881
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000
    watermark_col: str = ""


class OceanBaseConnector:
    def __init__(self, config: OceanBaseConfig):
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
            doc.metadata["source_type"] = "oceanbase"
        return docs, cursor

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        docs, new_cursor = await self._inner.sync_incremental(cursor)
        for doc in docs:
            doc.metadata["source_type"] = "oceanbase"
        return docs, new_cursor
