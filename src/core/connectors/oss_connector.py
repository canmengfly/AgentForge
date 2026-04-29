"""Aliyun OSS connector — lists and downloads objects for indexing."""
from __future__ import annotations

import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice

from ..document_processor import ParsedDocument, _make_id, parse_file

_SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx", ".html", ".htm", ".csv"}


@dataclass
class OSSConfig:
    endpoint: str
    access_key_id: str
    access_key_secret: str
    bucket: str
    prefix: str = ""


class OSSConnector:
    def __init__(self, config: OSSConfig):
        self.config = config

    def _make_bucket(self):
        try:
            import oss2
        except ImportError as e:
            raise RuntimeError("oss2 required: pip install oss2") from e
        endpoint = self.config.endpoint.strip()
        if not endpoint.startswith("http"):
            endpoint = "https://" + endpoint
        auth = oss2.Auth(self.config.access_key_id, self.config.access_key_secret)
        return oss2.Bucket(auth, endpoint, self.config.bucket)

    def _test_sync(self) -> dict:
        try:
            bucket = self._make_bucket()
            import oss2
            list(islice(oss2.ObjectIterator(bucket, prefix=self.config.prefix or "", max_keys=1), 1))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _collect(self, since_mtime: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        """Scan bucket and return (docs, cursor).

        Only processes objects with last_modified > since_mtime.
        Pass since_mtime=0.0 for a full sync.
        """
        import oss2
        bucket = self._make_bucket()
        docs: list[ParsedDocument] = []
        max_mtime = since_mtime

        for obj in oss2.ObjectIterator(bucket, prefix=self.config.prefix or ""):
            obj_mtime = obj.last_modified  # Unix epoch float
            max_mtime = max(max_mtime, obj_mtime)
            if obj_mtime <= since_mtime:
                continue
            key = obj.key
            filename = key.rstrip("/").split("/")[-1]
            if not filename:
                continue
            suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
            if suffix not in _SUPPORTED_SUFFIXES:
                continue
            try:
                raw = bucket.get_object(key).read()
                doc = parse_file(io.BytesIO(raw), filename)
                doc.source = f"oss://{self.config.bucket}/{key}"
                doc.doc_id = _make_id(f"oss:{self.config.bucket}:{key}")
                doc.metadata.update({"oss_bucket": self.config.bucket, "oss_key": key})
                docs.append(doc)
            except Exception:
                continue

        # Cursor: record the max mtime seen (or current time if bucket was empty)
        cursor = {"last_mtime": max_mtime if max_mtime > 0 else time.time()}
        return docs, cursor

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        """Full sync — returns (all_docs, cursor)."""
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, 0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        """Incremental sync — returns only objects modified after cursor['last_mtime']."""
        since = cursor.get("last_mtime", 0.0)
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, since)
