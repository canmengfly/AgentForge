"""语雀（Yuque）连接器 — 通过语雀 API v2 同步文档。"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from ..document_processor import ParsedDocument, _make_id


@dataclass
class YuqueConfig:
    token: str
    namespace: str = ""                            # "user/repo"，留空同步所有可访问仓库
    base_url: str = "https://www.yuque.com"        # 私有部署可修改


class YuqueConnector:
    def __init__(self, config: YuqueConfig):
        self.config = config

    def _headers(self) -> dict:
        return {
            "X-Auth-Token": self.config.token,
            "Content-Type": "application/json",
            "User-Agent": "AgentForge/1.0",
        }

    def _api(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/api/v2/{path.lstrip('/')}"

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(self._api("user"), headers=self._headers())
                r.raise_for_status()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _list_namespaces(self, client: httpx.AsyncClient) -> list[str]:
        if self.config.namespace:
            return [self.config.namespace]
        # List user's own repos
        r = await client.get(self._api("mine/repos"), headers=self._headers(),
                             params={"type": "doc", "limit": 100})
        r.raise_for_status()
        repos = r.json().get("data", [])
        return [repo["namespace"] for repo in repos if repo.get("namespace")]

    async def _list_docs(self, client: httpx.AsyncClient, namespace: str) -> list[dict]:
        r = await client.get(self._api(f"repos/{namespace}/docs"),
                             headers=self._headers(), params={"limit": 100})
        r.raise_for_status()
        return r.json().get("data", [])

    async def _get_doc(self, client: httpx.AsyncClient, namespace: str, slug: str) -> str:
        r = await client.get(self._api(f"repos/{namespace}/docs/{slug}"),
                             headers=self._headers())
        r.raise_for_status()
        data = r.json().get("data", {})
        body_html = data.get("body_html") or data.get("body") or ""
        if not body_html:
            return ""
        from bs4 import BeautifulSoup
        return BeautifulSoup(body_html, "html.parser").get_text("\n", strip=True)

    async def _collect(self, since_ts: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        docs: list[ParsedDocument] = []
        max_ts = since_ts

        async with httpx.AsyncClient(timeout=30) as client:
            namespaces = await self._list_namespaces(client)
            for ns in namespaces:
                try:
                    doc_list = await self._list_docs(client, ns)
                except Exception:
                    continue
                for item in doc_list:
                    updated_at = item.get("updated_at") or item.get("content_updated_at") or ""
                    try:
                        import datetime
                        item_ts = datetime.datetime.fromisoformat(
                            updated_at.replace("Z", "+00:00")
                        ).timestamp() if updated_at else 0.0
                    except Exception:
                        item_ts = 0.0
                    max_ts = max(max_ts, item_ts)
                    if item_ts > 0 and item_ts <= since_ts:
                        continue
                    slug = item.get("slug") or item.get("id") or ""
                    title = item.get("title") or "Untitled"
                    if not slug:
                        continue
                    try:
                        content = await self._get_doc(client, ns, str(slug))
                    except Exception:
                        continue
                    if not content.strip():
                        continue
                    docs.append(ParsedDocument(
                        doc_id=_make_id(f"yuque:{ns}:{slug}"),
                        title=title,
                        source=f"{self.config.base_url.rstrip('/')}/{ns}/{slug}",
                        content=content,
                        metadata={
                            "source_type": "yuque",
                            "namespace": ns,
                            "slug": str(slug),
                        },
                    ))

        cursor = {"last_ts": max_ts if max_ts > 0 else time.time()}
        return docs, cursor

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(cursor.get("last_ts", 0.0))
