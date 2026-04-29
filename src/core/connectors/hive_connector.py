"""Apache Hive connector — queries tables via PyHive (Thrift/HiveServer2)."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..document_processor import ParsedDocument, _make_id


@dataclass
class HiveConfig:
    host: str
    database: str = "default"
    username: str = ""
    password: str = ""
    port: int = 10000
    tables: list[str] = field(default_factory=list)
    row_limit: int = 5000
    auth: str = "NOSASL"    # NOSASL | LDAP | KERBEROS


class HiveConnector:
    def __init__(self, config: HiveConfig):
        self.config = config

    def _make_connection(self):
        try:
            from pyhive import hive
        except ImportError as e:
            raise RuntimeError("pyhive[hive] required: pip install pyhive[hive] thrift") from e

        kwargs: dict = {
            "host": self.config.host,
            "port": self.config.port,
            "database": self.config.database,
            "auth": self.config.auth,
        }
        if self.config.username:
            kwargs["username"] = self.config.username
        if self.config.password and self.config.auth == "LDAP":
            kwargs["password"] = self.config.password
        return hive.connect(**kwargs)

    def _test_sync(self) -> dict:
        try:
            conn = self._make_connection()
            cur = conn.cursor()
            cur.execute("SHOW TABLES")
            cur.fetchone()
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
        cursor.execute("SHOW TABLES")
        return [row[0] for row in cursor.fetchall()]

    def _collect(self, since_ts: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        conn = self._make_connection()
        cur = conn.cursor()
        docs: list[ParsedDocument] = []

        try:
            tables = self._list_tables(cur)
            for table in tables:
                try:
                    cur.execute(f"SELECT * FROM `{self.config.database}`.`{table}` LIMIT {self.config.row_limit}")
                    columns = [desc[0] for desc in cur.description]
                    for row in cur.fetchall():
                        record = dict(zip(columns, row))
                        doc = self._row_to_doc(record, table)
                        if doc:
                            docs.append(doc)
                except Exception:
                    continue
        finally:
            conn.close()

        cursor = {"last_ts": time.time()}
        return docs, cursor

    def _row_to_doc(self, record: dict, table: str) -> ParsedDocument | None:
        parts = [f"{k}: {v}" for k, v in record.items() if v is not None]
        content = "\n".join(parts)
        if not content.strip():
            return None

        row_key = str(record.get("id") or hash(content))
        doc_key = f"hive:{self.config.database}:{table}:{row_key}"
        title = str(record.get("title") or record.get("name") or f"{table}/{row_key}")
        doc = ParsedDocument(
            doc_id=_make_id(doc_key),
            title=title,
            source=f"hive://{self.config.host}/{self.config.database}/{table}",
            content=content,
            metadata={
                "source_type": "hive",
                "hive_database": self.config.database,
                "hive_table": table,
            },
        )
        return doc

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, 0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        # Hive doesn't have cheap change-data-capture; fall back to full sync
        return await self.sync_documents()
