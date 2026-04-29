"""MongoDB connector — fetches documents from one or more collections."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..document_processor import ParsedDocument, _make_id


@dataclass
class MongoDBConfig:
    uri: str                              # mongodb://user:pass@host:27017/dbname
    database: str
    collections: list[str] = field(default_factory=list)   # empty = all non-system
    text_fields: list[str] = field(default_factory=list)   # empty = all string fields
    timestamp_field: str = "updated_at"


class MongoDBConnector:
    def __init__(self, config: MongoDBConfig):
        self.config = config

    def _make_client(self):
        try:
            import pymongo
        except ImportError as e:
            raise RuntimeError("pymongo required: pip install pymongo") from e
        return pymongo.MongoClient(self.config.uri)

    def _test_sync(self) -> dict:
        try:
            client = self._make_client()
            client[self.config.database].list_collection_names()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _collect(self, since_ts: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        client = self._make_client()
        db = client[self.config.database]
        col_names = self.config.collections or [
            n for n in db.list_collection_names() if not n.startswith("system.")
        ]

        docs: list[ParsedDocument] = []
        max_ts = since_ts

        for col_name in col_names:
            col = db[col_name]
            query: dict = {}
            if since_ts > 0 and self.config.timestamp_field:
                import datetime
                query = {self.config.timestamp_field: {"$gt": datetime.datetime.utcfromtimestamp(since_ts)}}

            for record in col.find(query):
                ts = self._extract_ts(record)
                if ts:
                    max_ts = max(max_ts, ts)
                doc = self._record_to_doc(record, col_name)
                if doc:
                    docs.append(doc)

        cursor = {"last_ts": max_ts if max_ts > 0 else time.time()}
        return docs, cursor

    def _extract_ts(self, record: dict) -> float:
        val = record.get(self.config.timestamp_field)
        if val is None:
            return 0.0
        try:
            import datetime
            if isinstance(val, datetime.datetime):
                return val.timestamp()
            return float(val)
        except Exception:
            return 0.0

    def _record_to_doc(self, record: dict, col_name: str) -> ParsedDocument | None:
        rec_id = str(record.get("_id", ""))
        if self.config.text_fields:
            parts = [str(record[f]) for f in self.config.text_fields if f in record and record[f]]
        else:
            parts = [f"{k}: {v}" for k, v in record.items() if k != "_id" and v is not None]
        content = "\n".join(parts)
        if not content.strip():
            return None

        doc_key = f"mongo:{self.config.database}:{col_name}:{rec_id}"
        title = str(record.get("title") or record.get("name") or f"{col_name}/{rec_id}")
        doc = ParsedDocument(
            doc_id=_make_id(doc_key),
            title=title,
            source=f"mongodb://{self.config.database}/{col_name}/{rec_id}",
            content=content,
            metadata={
                "source_type": "mongodb",
                "mongo_db": self.config.database,
                "mongo_collection": col_name,
                "mongo_id": rec_id,
            },
        )
        return doc

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, 0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        since = cursor.get("last_ts", 0.0)
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, since)
