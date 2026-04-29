"""AWS S3 / S3-compatible (MinIO etc.) connector — mirrors the OSSConnector design."""
from __future__ import annotations

import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ..document_processor import ParsedDocument, _make_id, parse_file

_SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx", ".html", ".htm", ".csv"}


@dataclass
class S3Config:
    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str = "us-east-1"
    prefix: str = ""
    endpoint_url: str = ""      # for MinIO / custom S3-compatible endpoints


class S3Connector:
    def __init__(self, config: S3Config):
        self.config = config

    def _make_client(self):
        try:
            import boto3
        except ImportError as e:
            raise RuntimeError("boto3 required: pip install boto3") from e
        kwargs: dict = {
            "aws_access_key_id": self.config.access_key_id,
            "aws_secret_access_key": self.config.secret_access_key,
            "region_name": self.config.region,
        }
        if self.config.endpoint_url:
            kwargs["endpoint_url"] = self.config.endpoint_url
        return boto3.client("s3", **kwargs)

    def _test_sync(self) -> dict:
        try:
            client = self._make_client()
            client.head_bucket(Bucket=self.config.bucket)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def test_connection(self) -> dict:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            return await loop.run_in_executor(pool, self._test_sync)

    def _collect(self, since_mtime: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        client = self._make_client()
        docs: list[ParsedDocument] = []
        max_mtime = since_mtime
        paginator = client.get_paginator("list_objects_v2")

        for page in paginator.paginate(
            Bucket=self.config.bucket,
            Prefix=self.config.prefix or "",
        ):
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                obj_mtime: float = obj["LastModified"].timestamp()
                max_mtime = max(max_mtime, obj_mtime)
                if obj_mtime <= since_mtime:
                    continue
                filename = key.rstrip("/").split("/")[-1]
                if not filename:
                    continue
                suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
                if suffix not in _SUPPORTED_SUFFIXES:
                    continue
                try:
                    raw = client.get_object(Bucket=self.config.bucket, Key=key)["Body"].read()
                    doc = parse_file(io.BytesIO(raw), filename)
                    doc.source = f"s3://{self.config.bucket}/{key}"
                    doc.doc_id = _make_id(f"s3:{self.config.bucket}:{key}")
                    doc.metadata.update({
                        "s3_bucket": self.config.bucket,
                        "s3_key": key,
                        "source_type": "s3",
                    })
                    docs.append(doc)
                except Exception:
                    continue

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
