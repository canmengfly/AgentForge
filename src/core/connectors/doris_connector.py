"""Apache Doris connector — thin wrapper over SQLConnector (MySQL-wire protocol, default port 9030)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .sql_connector import SQLConnector, SQLConfig
from ..document_processor import ParsedDocument


@dataclass
class DorisConfig:
    host: str
    database: str
    username: str
    password: str
    port: int = 9030
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000


class DorisConnector:
    """Wraps SQLConnector with the MySQL driver and Doris defaults."""

    def __init__(self, config: DorisConfig):
        self._inner = SQLConnector(SQLConfig(
            driver="mysql",
            host=config.host,
            port=config.port,
            database=config.database,
            username=config.username,
            password=config.password,
            tables=config.tables,
            row_limit=config.row_limit,
        ))
        # Tag documents with doris source_type after delegation
        self._config = config

    async def test_connection(self) -> dict:
        return await self._inner.test_connection()

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        docs, cursor = await self._inner.sync_documents()
        for doc in docs:
            doc.metadata["source_type"] = "doris"
        return docs, cursor

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        docs, new_cursor = await self._inner.sync_incremental(cursor)
        for doc in docs:
            doc.metadata["source_type"] = "doris"
        return docs, new_cursor
