"""钉钉文档连接器 — 基于钉钉开放平台 v1.0 Doc API

所需权限（钉钉开放平台 → 应用 → 权限管理）:
  doc:doc                     读取钉钉文档（知识库）

参考文档:
  https://open.dingtalk.com/document/orgapp/obtain-the-access_token-of-an-internal-app
  https://open.dingtalk.com/document/orgapp/doc-api-overview
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from ..document_processor import ParsedDocument, _make_id

_OLD_BASE = "https://oapi.dingtalk.com"
_NEW_BASE = "https://api.dingtalk.com/v1.0"


@dataclass
class DingTalkConfig:
    app_key: str
    app_secret: str
    workspace_id: str = ""   # 知识库 workspaceId，留空则同步全部


class DingTalkConnector:
    def __init__(self, config: DingTalkConfig):
        self.config = config
        self._token: str | None = None
        self._token_exp: float = 0.0

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 120:
            return self._token
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{_OLD_BASE}/gettoken",
                params={"appkey": self.config.app_key, "appsecret": self.config.app_secret},
            )
            r.raise_for_status()
            body = r.json()
            if body.get("errcode") != 0:
                raise RuntimeError(f"钉钉授权失败: {body.get('errmsg')}")
            self._token = body["access_token"]
            self._token_exp = time.time() + body.get("expires_in", 7200)
        return self._token  # type: ignore[return-value]

    def _auth(self, token: str) -> dict:
        return {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}

    # ── Connection test ───────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"{_NEW_BASE}/doc/workspaces",
                    headers=self._auth(token),
                    params={"maxResults": 1},
                )
                r.raise_for_status()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── List helpers ─────────────────────────────────────────────────────────

    async def _list_workspaces(self, client: httpx.AsyncClient, token: str) -> list[str]:
        if self.config.workspace_id:
            return [self.config.workspace_id]
        workspace_ids: list[str] = []
        next_token = ""
        while True:
            params: dict = {"maxResults": 50}
            if next_token:
                params["nextToken"] = next_token
            r = await client.get(
                f"{_NEW_BASE}/doc/workspaces",
                headers=self._auth(token),
                params=params,
            )
            r.raise_for_status()
            result = r.json().get("result", {})
            for ws in result.get("workspaces", []):
                workspace_ids.append(ws["workspaceId"])
            next_token = result.get("nextToken", "")
            if not result.get("hasMore"):
                break
        return workspace_ids

    async def _list_nodes(
        self, client: httpx.AsyncClient, token: str, workspace_id: str, parent_id: str = ""
    ) -> list[dict]:
        """递归列出工作空间内所有文档节点。"""
        nodes: list[dict] = []
        next_token = ""
        while True:
            params: dict = {"workspaceId": workspace_id, "maxResults": 50}
            if next_token:
                params["nextToken"] = next_token
            if parent_id:
                params["parentNodeId"] = parent_id
            r = await client.get(
                f"{_NEW_BASE}/doc/workspaces/{workspace_id}/nodes",
                headers=self._auth(token),
                params=params,
            )
            r.raise_for_status()
            result = r.json().get("result", {})
            for node in result.get("nodes", []):
                nodes.append(node)
                if node.get("hasChildren"):
                    children = await self._list_nodes(client, token, workspace_id, node["nodeId"])
                    nodes.extend(children)
            next_token = result.get("nextToken", "")
            if not result.get("hasMore"):
                break
        return nodes

    async def _get_content(
        self, client: httpx.AsyncClient, token: str, doc_id: str
    ) -> str:
        """获取钉钉文档纯文本内容。"""
        try:
            r = await client.get(
                f"{_NEW_BASE}/doc/docs/{doc_id}/content",
                headers=self._auth(token),
            )
            r.raise_for_status()
            result = r.json().get("result", {})
            # content 可能在不同字段，兼容处理
            return (
                result.get("content")
                or result.get("markdownContent")
                or result.get("textContent")
                or ""
            )
        except Exception:
            return ""

    # ── Sync ─────────────────────────────────────────────────────────────────

    async def _collect(self, since_mtime: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        token = await self._get_token()
        docs: list[ParsedDocument] = []
        max_mtime = since_mtime

        async with httpx.AsyncClient(timeout=30) as client:
            workspace_ids = await self._list_workspaces(client, token)
            for workspace_id in workspace_ids:
                nodes = await self._list_nodes(client, token, workspace_id)
                for node in nodes:
                    # 只处理文档类型节点（排除文件夹）
                    node_type = node.get("nodeType", "")
                    if node_type not in ("doc", ""):
                        continue

                    try:
                        modified_ts = float(node.get("modifyTime") or node.get("createTime") or 0)
                    except (ValueError, TypeError):
                        modified_ts = 0.0

                    max_mtime = max(max_mtime, modified_ts)
                    if modified_ts <= since_mtime:
                        continue

                    doc_id_raw = node.get("docId") or node.get("nodeId", "")
                    title = node.get("name") or node.get("title") or "未命名"

                    content = await self._get_content(client, token, doc_id_raw)
                    if not content.strip():
                        continue

                    docs.append(ParsedDocument(
                        doc_id=_make_id(f"dingtalk:{workspace_id}:{doc_id_raw}"),
                        title=title,
                        source=f"dingtalk://workspace/{workspace_id}/{doc_id_raw}",
                        content=content,
                        metadata={
                            "workspace_id": workspace_id,
                            "doc_id": doc_id_raw,
                            "source_type": "dingtalk",
                        },
                    ))

        cursor = {"last_mtime": max_mtime if max_mtime > 0 else time.time()}
        return docs, cursor

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(cursor.get("last_mtime", 0.0))
