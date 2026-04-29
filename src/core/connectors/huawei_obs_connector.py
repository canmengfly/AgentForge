"""华为云 OBS 连接器 — 基于 esdk-obs-python。"""
from __future__ import annotations

import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ..document_processor import ParsedDocument, _make_id, parse_file

_SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx", ".html", ".htm", ".csv"}


@dataclass
class HuaweiOBSConfig:
    access_key_id: str
    secret_access_key: str
    endpoint: str           # e.g. "https://obs.cn-north-4.myhuaweicloud.com"
    bucket: str
    prefix: str = ""


class HuaweiOBSConnector:
    def __init__(self, config: HuaweiOBSConfig):
        self.config = config

    def _make_client(self):
        try:
            from obs import ObsClient
        except ImportError as e:
            raise RuntimeError(
                "esdk-obs-python required: pip install esdk-obs-python"
            ) from e
        return ObsClient(
            access_key_id=self.config.access_key_id,
            secret_access_key=self.config.secret_access_key,
            server=self.config.endpoint,
        )

    def _test_sync(self) -> dict:
        try:
            client = self._make_client()
            resp = client.headBucket(self.config.bucket)
            if resp.status < 300:
                return {"ok": True}
            return {"ok": False, "error": f"HTTP {resp.status}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _collect(self, since_ts: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        client = self._make_client()
        docs: list[ParsedDocument] = []
        max_mtime = since_ts
        marker = None

        while True:
            params: dict = {
                "bucketName": self.config.bucket,
                "prefix": self.config.prefix or None,
                "max_keys": 1000,
            }
            if marker:
                params["marker"] = marker
            resp = client.listObjects(**params)
            if resp.status >= 300:
                break

            for obj in resp.body.contents or []:
                key: str = obj.key
                try:
                    import datetime
                    mtime = datetime.datetime.fromisoformat(
                        obj.lastModified.replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    mtime = time.time()
                max_mtime = max(max_mtime, mtime)
                if mtime <= since_ts:
                    continue
                filename = key.rstrip("/").split("/")[-1]
                if not filename:
                    continue
                ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
                if ext not in _SUPPORTED_SUFFIXES:
                    continue
                try:
                    get_resp = client.getObject(self.config.bucket, key, loadStreamInMemory=True)
                    if get_resp.status >= 300:
                        continue
                    raw = get_resp.body.buffer
                    doc = parse_file(io.BytesIO(raw), filename)
                    doc.source = f"obs://{self.config.bucket}/{key}"
                    doc.doc_id = _make_id(f"obs:{self.config.bucket}:{key}")
                    doc.metadata.update({
                        "source_type": "huawei_obs",
                        "obs_bucket": self.config.bucket,
                        "obs_key": key,
                    })
                    docs.append(doc)
                except Exception:
                    continue

            if resp.body.is_truncated:
                marker = resp.body.next_marker
            else:
                break

        cursor = {"last_mtime": max_mtime if max_mtime > 0 else time.time()}
        return docs, cursor

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, 0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        since = cursor.get("last_mtime", 0.0)
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._collect, since)
