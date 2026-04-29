"""腾讯云 COS 连接器 — 基于 cos-python-sdk-v5。"""
from __future__ import annotations

import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ..document_processor import ParsedDocument, _make_id, parse_file

_SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx", ".html", ".htm", ".csv"}


@dataclass
class TencentCOSConfig:
    region: str             # e.g. "ap-beijing"
    secret_id: str
    secret_key: str
    bucket: str             # name-appid, e.g. "mybucket-1234567890"
    prefix: str = ""


class TencentCOSConnector:
    def __init__(self, config: TencentCOSConfig):
        self.config = config

    def _make_client(self):
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ImportError as e:
            raise RuntimeError(
                "cos-python-sdk-v5 required: pip install cos-python-sdk-v5"
            ) from e
        cos_cfg = CosConfig(
            Region=self.config.region,
            SecretId=self.config.secret_id,
            SecretKey=self.config.secret_key,
        )
        return CosS3Client(cos_cfg)

    def _test_sync(self) -> dict:
        try:
            client = self._make_client()
            client.head_bucket(Bucket=self.config.bucket)
            return {"ok": True}
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
        marker = ""

        while True:
            resp = client.list_objects(
                Bucket=self.config.bucket,
                Prefix=self.config.prefix or "",
                Marker=marker,
                MaxKeys=1000,
            )
            for obj in resp.get("Contents", []):
                key: str = obj["Key"]
                # COS LastModified is ISO 8601 string
                try:
                    import datetime
                    mtime = datetime.datetime.fromisoformat(
                        obj["LastModified"].replace("Z", "+00:00")
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
                    raw_resp = client.get_object(Bucket=self.config.bucket, Key=key)
                    raw = raw_resp["Body"].get_raw_stream().read()
                    doc = parse_file(io.BytesIO(raw), filename)
                    doc.source = f"cos://{self.config.bucket}/{key}"
                    doc.doc_id = _make_id(f"cos:{self.config.bucket}:{key}")
                    doc.metadata.update({
                        "source_type": "tencent_cos",
                        "cos_bucket": self.config.bucket,
                        "cos_key": key,
                    })
                    docs.append(doc)
                except Exception:
                    continue

            if resp.get("IsTruncated") == "true":
                marker = resp.get("NextMarker", "")
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
