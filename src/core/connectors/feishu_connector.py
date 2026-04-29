"""飞书文档连接器 — 基于飞书开放平台 Wiki API v2 / Docx API v1

所需权限（在飞书开放平台 → 应用 → 权限管理 中开启）:
  wiki:wiki:readonly          读取知识空间
  docx:document:readonly      读取文档内容（新版 docx）
  doc:doc:readonly            读取文档内容（旧版 doc，可选）

参考文档:
  https://open.feishu.cn/document/server-docs/docs/wiki-v2/wiki-overview
  https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/raw_content
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from ..document_processor import ParsedDocument, _make_id

_BASE = "https://open.feishu.cn/open-apis"


@dataclass
class FeishuConfig:
    app_id: str
    app_secret: str
    space_id: str = ""   # 知识空间 ID，留空则同步所有 space


class FeishuConnector:
    def __init__(self, config: FeishuConfig):
        self.config = config
        self._token: str | None = None
        self._token_exp: float = 0.0

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 120:
            return self._token
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            )
            r.raise_for_status()
            body = r.json()
            if body.get("code") != 0:
                raise RuntimeError(f"飞书授权失败: {body.get('msg')}")
            self._token = body["tenant_access_token"]
            self._token_exp = time.time() + body.get("expire", 7200)
        return self._token  # type: ignore[return-value]

    def _auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    # ── Connection test ───────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        try:
            await self._get_token()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── List helpers ─────────────────────────────────────────────────────────

    async def _list_spaces(self, client: httpx.AsyncClient, token: str) -> list[str]:
        if self.config.space_id:
            return [self.config.space_id]
        space_ids: list[str] = []
        page_token = ""
        while True:
            params: dict = {"page_size": 50}
            if page_token:
                params["page_token"] = page_token
            r = await client.get(f"{_BASE}/wiki/v2/spaces", headers=self._auth(token), params=params)
            r.raise_for_status()
            data = r.json().get("data", {})
            for item in data.get("items", []):
                space_ids.append(item["space_id"])
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
        return space_ids

    async def _list_nodes(
        self,
        client: httpx.AsyncClient,
        token: str,
        space_id: str,
        parent_token: str = "",
    ) -> list[dict]:
        """递归列出空间内所有文档节点。"""
        nodes: list[dict] = []
        page_token = ""
        while True:
            params: dict = {"page_size": 50}
            if page_token:
                params["page_token"] = page_token
            if parent_token:
                params["parent_node_token"] = parent_token
            r = await client.get(
                f"{_BASE}/wiki/v2/spaces/{space_id}/nodes",
                headers=self._auth(token),
                params=params,
            )
            r.raise_for_status()
            data = r.json().get("data", {})
            for item in data.get("items", []):
                nodes.append(item)
                if item.get("has_child"):
                    children = await self._list_nodes(client, token, space_id, item["node_token"])
                    nodes.extend(children)
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
        return nodes

    async def _get_content(
        self, client: httpx.AsyncClient, token: str, obj_token: str, obj_type: str
    ) -> str:
        try:
            if obj_type == "docx":
                url = f"{_BASE}/docx/v1/documents/{obj_token}/raw_content"
            elif obj_type == "doc":
                url = f"{_BASE}/doc/v2/{obj_token}/raw_content"
            else:
                return ""
            r = await client.get(url, headers=self._auth(token))
            r.raise_for_status()
            return r.json().get("data", {}).get("content", "")
        except Exception:
            return ""

    # ── Sync ─────────────────────────────────────────────────────────────────

    async def _collect(self, since_mtime: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        token = await self._get_token()
        docs: list[ParsedDocument] = []
        max_mtime = since_mtime

        async with httpx.AsyncClient(timeout=30) as client:
            space_ids = await self._list_spaces(client, token)
            for space_id in space_ids:
                nodes = await self._list_nodes(client, token, space_id)
                for node in nodes:
                    obj_type = node.get("obj_type", "")
                    if obj_type not in ("docx", "doc"):
                        continue
                    try:
                        edit_mtime = float(node.get("obj_edit_time") or 0)
                    except (ValueError, TypeError):
                        edit_mtime = 0.0
                    max_mtime = max(max_mtime, edit_mtime)
                    if edit_mtime <= since_mtime:
                        continue

                    obj_token = node.get("obj_token", "")
                    title = node.get("title") or "未命名"
                    content = await self._get_content(client, token, obj_token, obj_type)
                    if not content.strip():
                        continue

                    docs.append(ParsedDocument(
                        doc_id=_make_id(f"feishu:{space_id}:{obj_token}"),
                        title=title,
                        source=f"feishu://wiki/{space_id}/{obj_token}",
                        content=content,
                        metadata={
                            "space_id": space_id,
                            "obj_token": obj_token,
                            "obj_type": obj_type,
                            "source_type": "feishu",
                        },
                    ))

        cursor = {"last_mtime": max_mtime if max_mtime > 0 else time.time()}
        return docs, cursor

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(cursor.get("last_mtime", 0.0))
