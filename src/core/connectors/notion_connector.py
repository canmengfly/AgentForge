"""Notion connector — fetches pages and database rows via Notion API v1."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from ..document_processor import ParsedDocument, _make_id

_NOTION_VERSION = "2022-06-28"
_BASE = "https://api.notion.com/v1"


@dataclass
class NotionConfig:
    token: str                                        # Integration secret
    database_ids: list[str] = field(default_factory=list)  # empty = search all
    page_ids: list[str] = field(default_factory=list)


class NotionConnector:
    def __init__(self, config: NotionConfig):
        self.config = config

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{_BASE}/users/me", headers=self._headers())
                r.raise_for_status()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Block text extraction ─────────────────────────────────────────────────

    def _rich_text(self, rich_texts: list[dict]) -> str:
        return "".join(rt.get("plain_text", "") for rt in rich_texts)

    def _block_text(self, block: dict) -> str:
        btype = block.get("type", "")
        data = block.get(btype, {})
        # Most block types have "rich_text"
        rt = data.get("rich_text", [])
        text = self._rich_text(rt)
        # Table rows
        if btype == "table_row":
            cells = data.get("cells", [])
            text = " | ".join(self._rich_text(cell) for cell in cells)
        return text

    async def _get_block_text(self, client: httpx.AsyncClient, block_id: str, depth: int = 0) -> str:
        if depth > 3:
            return ""
        texts: list[str] = []
        cursor = None
        while True:
            params: dict = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            r = await client.get(f"{_BASE}/blocks/{block_id}/children",
                                 headers=self._headers(), params=params)
            if r.status_code != 200:
                break
            data = r.json()
            for block in data.get("results", []):
                t = self._block_text(block)
                if t:
                    texts.append(t)
                if block.get("has_children"):
                    child_text = await self._get_block_text(client, block["id"], depth + 1)
                    if child_text:
                        texts.append(child_text)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return "\n".join(texts)

    # ── Search all accessible pages ───────────────────────────────────────────

    async def _search_pages(
        self, client: httpx.AsyncClient, since_iso: str | None
    ) -> list[dict]:
        pages: list[dict] = []
        cursor = None
        while True:
            body: dict = {"page_size": 100, "filter": {"value": "page", "property": "object"}}
            if cursor:
                body["start_cursor"] = cursor
            r = await client.post(f"{_BASE}/search", headers=self._headers(), json=body)
            r.raise_for_status()
            data = r.json()
            for obj in data.get("results", []):
                if since_iso and obj.get("last_edited_time", "") <= since_iso:
                    continue
                pages.append(obj)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return pages

    def _page_title(self, page: dict) -> str:
        props = page.get("properties", {})
        for key in ("Name", "Title", "title", "name"):
            prop = props.get(key, {})
            if prop.get("type") == "title":
                rt = prop.get("title", [])
                t = "".join(r.get("plain_text", "") for r in rt)
                if t:
                    return t
        return "Untitled"

    async def _collect(self, since_iso: str | None = None) -> tuple[list[ParsedDocument], dict]:
        docs: list[ParsedDocument] = []
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        seen: set[str] = set()

        async with httpx.AsyncClient(timeout=30) as client:
            # If specific IDs configured, fetch those directly
            targets = list(self.config.page_ids)
            if not targets and not self.config.database_ids:
                # Search everything
                pages = await self._search_pages(client, since_iso)
                targets = [p["id"] for p in pages]
                page_meta = {p["id"]: p for p in pages}
            else:
                page_meta = {}

            for db_id in self.config.database_ids:
                # Query database pages
                db_cursor = None
                while True:
                    body: dict = {"page_size": 100}
                    if since_iso:
                        body["filter"] = {
                            "property": "last_edited_time",
                            "last_edited_time": {"after": since_iso},
                        }
                    if db_cursor:
                        body["start_cursor"] = db_cursor
                    r = await client.post(f"{_BASE}/databases/{db_id}/query",
                                          headers=self._headers(), json=body)
                    if r.status_code != 200:
                        break
                    data = r.json()
                    for p in data.get("results", []):
                        targets.append(p["id"])
                        page_meta[p["id"]] = p
                    if not data.get("has_more"):
                        break
                    db_cursor = data.get("next_cursor")

            for page_id in targets:
                if page_id in seen:
                    continue
                seen.add(page_id)
                try:
                    meta = page_meta.get(page_id)
                    if meta is None:
                        r = await client.get(f"{_BASE}/pages/{page_id}", headers=self._headers())
                        if r.status_code != 200:
                            continue
                        meta = r.json()
                    title = self._page_title(meta)
                    content = await self._get_block_text(client, page_id)
                    if not content.strip():
                        continue
                    docs.append(ParsedDocument(
                        doc_id=_make_id(f"notion:{page_id}"),
                        title=title,
                        source=f"https://notion.so/{page_id.replace('-', '')}",
                        content=content,
                        metadata={"source_type": "notion", "page_id": page_id},
                    ))
                except Exception:
                    continue

        return docs, {"last_iso": now_iso}

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(None)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(cursor.get("last_iso"))
