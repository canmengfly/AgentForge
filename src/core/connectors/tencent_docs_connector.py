"""腾讯文档连接器 — 基于腾讯文档开放平台 Drive API v2

腾讯文档采用用户级 OAuth2 鉴权，需手动在开放平台完成授权后提供 access_token。
若同时提供 refresh_token，连接器会在 token 过期前自动续期。

获取 Token 步骤:
  1. 登录 https://docs.qq.com/open/wiki/ 创建应用，获取 client_id / client_secret
  2. 引导用户完成 OAuth2 授权码流程，获取 access_token + refresh_token
  3. 将 access_token 与 refresh_token 填入数据源配置

参考文档:
  https://docs.qq.com/open/wiki/
  https://docs.qq.com/open/wiki/api_reference/drive/list_files.html
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from ..document_processor import ParsedDocument, _make_id

_BASE = "https://docs.qq.com/openapi"
_TOKEN_URL = "https://docs.qq.com/oauth/v2/token"

# 腾讯文档支持导出的文件类型
_EXPORTABLE = {"document", "spreadsheet", "presentation"}


@dataclass
class TencentDocsConfig:
    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str = ""
    folder_id: str = ""    # 文件夹 ID，留空则同步根目录全部文档


class TencentDocsConnector:
    def __init__(self, config: TencentDocsConfig):
        self.config = config
        self._access_token = config.access_token
        self._token_exp: float = 0.0  # 0 = unknown, trigger refresh on first 401

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def _refresh(self) -> None:
        if not self.config.refresh_token:
            return  # can't refresh without refresh_token
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "refresh_token": self.config.refresh_token,
                },
            )
            r.raise_for_status()
            body = r.json()
            if body.get("error"):
                raise RuntimeError(f"腾讯文档 Token 刷新失败: {body}")
            self._access_token = body["access_token"]
            self._token_exp = time.time() + int(body.get("expires_in", 7200))
            if body.get("refresh_token"):
                self.config.refresh_token = body["refresh_token"]

    def _headers(self) -> dict:
        return {
            "Access-Token": self._access_token,
            "ClientId": self.config.client_id,
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(method, url, headers=self._headers(), **kwargs)
            if r.status_code == 401 and self.config.refresh_token:
                await self._refresh()
                r = await c.request(method, url, headers=self._headers(), **kwargs)
            r.raise_for_status()
            return r

    # ── Connection test ───────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        try:
            r = await self._request("GET", f"{_BASE}/drive/v2/files", params={"limit": 1})
            r.json()  # parse to validate
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── List helpers ─────────────────────────────────────────────────────────

    async def _list_files(self, folder_id: str = "") -> list[dict]:
        files: list[dict] = []
        next_cursor = ""
        while True:
            params: dict = {"limit": 100}
            if folder_id:
                params["folderId"] = folder_id
            if next_cursor:
                params["cursor"] = next_cursor
            r = await self._request("GET", f"{_BASE}/drive/v2/files", params=params)
            data = r.json().get("data", {})
            for f in data.get("files", []):
                files.append(f)
                # 递归进入子文件夹
                if f.get("fileType") == "folder":
                    sub = await self._list_files(f["id"])
                    files.extend(sub)
            next_cursor = data.get("nextCursor", "")
            if not data.get("hasMore"):
                break
        return files

    async def _export_content(self, doc_id: str, file_type: str) -> str:
        """以纯文本格式导出文档内容。"""
        try:
            r = await self._request(
                "GET",
                f"{_BASE}/drive/v2/export",
                params={"docID": doc_id, "exportType": "txt"},
            )
            # 返回可能是重定向到下载链接，或直接是文本
            content_type = r.headers.get("content-type", "")
            if "json" in content_type:
                body = r.json()
                # 部分接口返回下载 URL
                download_url = body.get("data", {}).get("url", "")
                if download_url:
                    async with httpx.AsyncClient(timeout=30) as c:
                        dr = await c.get(download_url)
                        return dr.text
                return ""
            return r.text
        except Exception:
            return ""

    # ── Sync ─────────────────────────────────────────────────────────────────

    async def _collect(self, since_ts: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        files = await self._list_files(self.config.folder_id)
        docs: list[ParsedDocument] = []
        max_ts = since_ts

        for f in files:
            file_type = f.get("fileType", "")
            if file_type not in _EXPORTABLE:
                continue

            try:
                updated_ts = float(f.get("updateTime") or f.get("createTime") or 0)
            except (ValueError, TypeError):
                updated_ts = 0.0

            max_ts = max(max_ts, updated_ts)
            if updated_ts <= since_ts:
                continue

            doc_id_raw = f.get("id", "")
            title = f.get("title") or f.get("name") or "未命名"
            content = await self._export_content(doc_id_raw, file_type)
            if not content.strip():
                continue

            docs.append(ParsedDocument(
                doc_id=_make_id(f"tencent_docs:{self.config.client_id}:{doc_id_raw}"),
                title=title,
                source=f"https://docs.qq.com/doc/{doc_id_raw}",
                content=content,
                metadata={
                    "doc_id": doc_id_raw,
                    "file_type": file_type,
                    "source_type": "tencent_docs",
                },
            ))

        cursor = {"last_ts": max_ts if max_ts > 0 else time.time()}
        return docs, cursor

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(cursor.get("last_ts", 0.0))
