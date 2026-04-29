"""SharePoint / OneDrive connector — Microsoft Graph API with client credentials."""
from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass, field

import httpx

from ..document_processor import ParsedDocument, _make_id, parse_file

_GRAPH = "https://graph.microsoft.com/v1.0"
_SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".html", ".htm", ".csv"}


@dataclass
class SharePointConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    site_url: str             # e.g. https://company.sharepoint.com/sites/wiki
    folder_path: str = ""     # specific library or subfolder, empty = root drive
    file_types: list[str] = field(default_factory=list)


class SharePointConnector:
    def __init__(self, config: SharePointConfig):
        self.config = config
        self._token: str | None = None
        self._token_exp: float = 0.0
        self._types = set(self.config.file_types) if self.config.file_types else _SUPPORTED

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_exp - 120:
            return self._token
        url = f"https://login.microsoftonline.com/{self.config.tenant_id}/oauth2/v2.0/token"
        resp = await client.post(url, data={
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        })
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_exp = time.time() + body.get("expires_in", 3600)
        return self._token  # type: ignore[return-value]

    def _auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    async def _get_site_id(self, client: httpx.AsyncClient, token: str) -> str:
        # Parse host and path from site_url
        from urllib.parse import urlparse
        parsed = urlparse(self.config.site_url)
        host = parsed.netloc
        site_path = parsed.path.rstrip("/")
        r = await client.get(
            f"{_GRAPH}/sites/{host}:{site_path}",
            headers=self._auth(token),
        )
        r.raise_for_status()
        return r.json()["id"]

    async def _list_items(
        self,
        client: httpx.AsyncClient,
        token: str,
        site_id: str,
    ) -> list[dict]:
        if self.config.folder_path:
            encoded = self.config.folder_path.replace("/", ":/").lstrip(":")
            base = f"{_GRAPH}/sites/{site_id}/drive/root:/{encoded}:/children"
        else:
            base = f"{_GRAPH}/sites/{site_id}/drive/root/children"

        items: list[dict] = []
        url: str | None = base
        while url:
            r = await client.get(url, headers=self._auth(token),
                                 params={"$top": 200, "$select": "id,name,file,lastModifiedDateTime"})
            r.raise_for_status()
            data = r.json()
            for item in data.get("value", []):
                if "file" not in item:  # skip folders
                    continue
                name: str = item.get("name", "")
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in self._types:
                    continue
                items.append(item)
            url = data.get("@odata.nextLink")
        return items

    async def _download(
        self,
        client: httpx.AsyncClient,
        token: str,
        site_id: str,
        item_id: str,
    ) -> bytes:
        r = await client.get(
            f"{_GRAPH}/sites/{site_id}/drive/items/{item_id}/content",
            headers=self._auth(token),
            follow_redirects=True,
        )
        r.raise_for_status()
        return r.content

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                token = await self._get_token(client)
                await self._get_site_id(client, token)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _collect(self, since_iso: str | None = None) -> tuple[list[ParsedDocument], dict]:
        docs: list[ParsedDocument] = []
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        async with httpx.AsyncClient(timeout=60) as client:
            token = await self._get_token(client)
            site_id = await self._get_site_id(client, token)
            items = await self._list_items(client, token, site_id)

            for item in items:
                if since_iso:
                    mtime = item.get("lastModifiedDateTime", "")
                    if mtime and mtime <= since_iso:
                        continue
                name: str = item["name"]
                item_id: str = item["id"]
                try:
                    raw = await self._download(client, token, site_id, item_id)
                    doc = parse_file(io.BytesIO(raw), name)
                    doc.source = f"{self.config.site_url}/{name}"
                    doc.doc_id = _make_id(f"sharepoint:{site_id}:{item_id}")
                    doc.metadata.update({
                        "source_type": "sharepoint",
                        "site_url": self.config.site_url,
                        "item_id": item_id,
                    })
                    docs.append(doc)
                except Exception:
                    continue

        return docs, {"last_iso": now_iso}

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(None)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(cursor.get("last_iso"))
