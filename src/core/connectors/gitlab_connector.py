"""GitLab connector — indexes Markdown/text files from one or more projects."""
from __future__ import annotations

import asyncio
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx

from ..document_processor import ParsedDocument, _make_id

_DEFAULT_TYPES = {".md", ".mdx", ".txt", ".rst"}


@dataclass
class GitLabConfig:
    token: str
    projects: list[str]          # ["group/project", ...] or ["123", ...]  (ID or path)
    branch: str = "main"
    path_prefix: str = ""
    file_types: list[str] = field(default_factory=list)
    base_url: str = "https://gitlab.com"


class GitLabConnector:
    def __init__(self, config: GitLabConfig):
        self.config = config
        self._types = (
            set(self.config.file_types) if self.config.file_types else _DEFAULT_TYPES
        )

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self.config.token}

    def _api(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/api/v4/{path.lstrip('/')}"

    def _encode(self, project: str) -> str:
        return urllib.parse.quote(project, safe="")

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(self._api("user"), headers=self._headers())
                r.raise_for_status()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _list_tree(self, client: httpx.AsyncClient, project: str) -> list[dict]:
        enc = self._encode(project)
        items: list[dict] = []
        page = 1
        while True:
            params: dict = {
                "ref": self.config.branch,
                "recursive": "true",
                "per_page": 100,
                "page": page,
            }
            if self.config.path_prefix:
                params["path"] = self.config.path_prefix
            r = await client.get(self._api(f"projects/{enc}/repository/tree"),
                                 headers=self._headers(), params=params)
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for item in batch:
                if item.get("type") != "blob":
                    continue
                path: str = item.get("path", "")
                ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
                if ext not in self._types:
                    continue
                items.append(item)
            if len(batch) < 100:
                break
            page += 1
        return items

    async def _get_content(
        self, client: httpx.AsyncClient, project: str, path: str
    ) -> str:
        enc_proj = self._encode(project)
        enc_path = urllib.parse.quote(path, safe="")
        r = await client.get(
            self._api(f"projects/{enc_proj}/repository/files/{enc_path}/raw"),
            headers=self._headers(),
            params={"ref": self.config.branch},
        )
        r.raise_for_status()
        return r.text

    async def _collect(self, since_ts: float = 0.0) -> tuple[list[ParsedDocument], dict]:
        docs: list[ParsedDocument] = []
        now = time.time()

        async with httpx.AsyncClient(timeout=30) as client:
            for project in self.config.projects:
                try:
                    tree = await self._list_tree(client, project)
                except Exception:
                    continue
                for item in tree:
                    path: str = item["path"]
                    title = path.rsplit("/", 1)[-1]
                    try:
                        content = await self._get_content(client, project, path)
                    except Exception:
                        continue
                    if not content.strip():
                        continue
                    docs.append(ParsedDocument(
                        doc_id=_make_id(f"gitlab:{project}:{self.config.branch}:{path}"),
                        title=title,
                        source=f"{self.config.base_url.rstrip('/')}/{project}/-/blob/{self.config.branch}/{path}",
                        content=content,
                        metadata={
                            "source_type": "gitlab",
                            "project": project,
                            "branch": self.config.branch,
                            "path": path,
                        },
                    ))

        return docs, {"last_ts": now}

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(cursor.get("last_ts", 0.0))
