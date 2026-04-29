"""Confluence connector — Cloud (Atlassian) and Server/Data Center via REST API v1."""
from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass, field

import httpx

from ..document_processor import ParsedDocument, _make_id

_SUPPORTED_TYPES = {"page", "blogpost"}


@dataclass
class ConfluenceConfig:
    base_url: str          # Cloud: https://mycompany.atlassian.net  Server: https://confluence.company.com
    username: str          # Cloud: email address  Server: username
    api_token: str         # Cloud: Atlassian API token  Server: password
    space_keys: list[str] = field(default_factory=list)   # empty = all spaces
    is_cloud: bool = True  # Cloud adds /wiki prefix to REST paths
    page_limit: int = 50


class ConfluenceConnector:
    def __init__(self, config: ConfluenceConfig):
        self.config = config

    def _api(self, path: str) -> str:
        prefix = "/wiki" if self.config.is_cloud else ""
        return f"{self.config.base_url.rstrip('/')}{prefix}/rest/api/{path.lstrip('/')}"

    def _auth_header(self) -> dict:
        creds = base64.b64encode(
            f"{self.config.username}:{self.config.api_token}".encode()
        ).decode()
        return {"Authorization": f"Basic {creds}", "Accept": "application/json"}

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(self._api("space"), headers=self._auth_header(),
                                params={"limit": 1})
                r.raise_for_status()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _list_space_keys(self, client: httpx.AsyncClient) -> list[str]:
        if self.config.space_keys:
            return self.config.space_keys
        keys: list[str] = []
        start = 0
        while True:
            r = await client.get(self._api("space"), headers=self._auth_header(),
                                 params={"limit": 50, "start": start})
            r.raise_for_status()
            body = r.json()
            results = body.get("results", [])
            for sp in results:
                keys.append(sp["key"])
            if not body.get("_links", {}).get("next"):
                break
            start += len(results)
        return keys

    async def _list_pages(
        self,
        client: httpx.AsyncClient,
        space_key: str,
        since_iso: str | None,
    ) -> list[dict]:
        pages: list[dict] = []
        start = 0
        while True:
            params: dict = {
                "type": "page",
                "spaceKey": space_key,
                "expand": "body.export_view,history.lastUpdated,version",
                "limit": self.config.page_limit,
                "start": start,
            }
            r = await client.get(self._api("content"), headers=self._auth_header(), params=params)
            r.raise_for_status()
            body = r.json()
            results = body.get("results", [])
            for p in results:
                if since_iso:
                    upd = p.get("history", {}).get("lastUpdated", {}).get("when", "")
                    if upd and upd <= since_iso:
                        continue
                pages.append(p)
            if not body.get("_links", {}).get("next"):
                break
            start += len(results)
        return pages

    def _page_to_doc(self, page: dict, space_key: str) -> ParsedDocument | None:
        from bs4 import BeautifulSoup
        title = page.get("title") or "Untitled"
        html = page.get("body", {}).get("export_view", {}).get("value", "")
        content = BeautifulSoup(html, "html.parser").get_text("\n", strip=True) if html else ""
        if not content.strip():
            return None
        page_id = page.get("id", "")
        return ParsedDocument(
            doc_id=_make_id(f"confluence:{self.config.base_url}:{space_key}:{page_id}"),
            title=title,
            source=f"{self.config.base_url.rstrip('/')}/wiki/spaces/{space_key}/pages/{page_id}",
            content=content,
            metadata={
                "source_type": "confluence",
                "space_key": space_key,
                "page_id": page_id,
            },
        )

    async def _collect(self, since_iso: str | None = None) -> tuple[list[ParsedDocument], dict]:
        docs: list[ParsedDocument] = []
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

        async with httpx.AsyncClient(timeout=30) as client:
            space_keys = await self._list_space_keys(client)
            for key in space_keys:
                pages = await self._list_pages(client, key, since_iso)
                for page in pages:
                    doc = self._page_to_doc(page, key)
                    if doc:
                        docs.append(doc)

        cursor = {"last_iso": now_iso}
        return docs, cursor

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(None)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(cursor.get("last_iso"))
