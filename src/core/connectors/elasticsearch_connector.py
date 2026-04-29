"""Elasticsearch connector — fetches documents via scroll API."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..document_processor import ParsedDocument, _make_id


@dataclass
class ElasticsearchConfig:
    hosts: list[str]          # e.g. ["http://localhost:9200"]
    index: str
    api_key: str = ""         # base64 id:api_key, or leave empty for no-auth
    username: str = ""
    password: str = ""
    text_fields: list[str] = field(default_factory=list)   # fields to concatenate as document body
    timestamp_field: str = "updated_at"                    # for incremental sync
    size: int = 500            # scroll batch size
    verify_certs: bool = True


class ElasticsearchConnector:
    def __init__(self, config: ElasticsearchConfig):
        self.config = config

    def _make_client(self):
        try:
            from elasticsearch import Elasticsearch
        except ImportError as e:
            raise RuntimeError("elasticsearch required: pip install elasticsearch") from e

        kwargs: dict = {
            "hosts": self.config.hosts,
            "verify_certs": self.config.verify_certs,
        }
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        elif self.config.username:
            kwargs["http_auth"] = (self.config.username, self.config.password)
        return Elasticsearch(**kwargs)

    def _test_sync(self) -> dict:
        try:
            es = self._make_client()
            if not es.indices.exists(index=self.config.index):
                return {"ok": False, "error": f"Index '{self.config.index}' not found"}
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _collect(self, since_ts: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        es = self._make_client()
        docs: list[ParsedDocument] = []
        max_ts = since_ts

        query: dict = {"query": {"match_all": {}}}
        if since_ts > 0 and self.config.timestamp_field:
            from datetime import datetime, timezone
            iso = datetime.fromtimestamp(since_ts, tz=timezone.utc).isoformat()
            query = {"query": {"range": {self.config.timestamp_field: {"gt": iso}}}}

        resp = es.search(
            index=self.config.index,
            body=query,
            size=self.config.size,
            scroll="2m",
        )
        scroll_id = resp["_scroll_id"]

        try:
            while True:
                hits = resp["hits"]["hits"]
                if not hits:
                    break
                for hit in hits:
                    doc = self._hit_to_doc(hit)
                    if doc:
                        docs.append(doc)
                        ts = self._extract_ts(hit)
                        if ts:
                            max_ts = max(max_ts, ts)
                resp = es.scroll(scroll_id=scroll_id, scroll="2m")
        finally:
            try:
                es.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass

        cursor = {"last_ts": max_ts if max_ts > 0 else time.time()}
        return docs, cursor

    def _extract_ts(self, hit: dict) -> float:
        src = hit.get("_source", {})
        val = src.get(self.config.timestamp_field)
        if not val:
            return 0.0
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            return 0.0

    def _hit_to_doc(self, hit: dict) -> ParsedDocument | None:
        src = hit.get("_source", {})
        if not src:
            return None
        if self.config.text_fields:
            parts = [str(src[f]) for f in self.config.text_fields if f in src and src[f]]
        else:
            parts = [f"{k}: {v}" for k, v in src.items() if v is not None]
        content = "\n".join(parts)
        if not content.strip():
            return None

        doc_key = f"es:{self.config.index}:{hit['_id']}"
        title = str(hit["_source"].get("title") or hit["_source"].get("name") or hit["_id"])
        doc = ParsedDocument(
            doc_id=_make_id(doc_key),
            title=title,
            source=f"es://{self.config.index}/{hit['_id']}",
            content=content,
            metadata={
                "source_type": "elasticsearch",
                "es_index": self.config.index,
                "es_id": hit["_id"],
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
