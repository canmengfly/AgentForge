"""GitHub connector — indexes Markdown/text files from one or more repositories."""
from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass, field

import httpx

from ..document_processor import ParsedDocument, _make_id

_DEFAULT_TYPES = {".md", ".mdx", ".txt", ".rst"}


@dataclass
class GitHubConfig:
    token: str
    repos: list[str]          # ["owner/repo", ...]
    branch: str = "main"
    path_prefix: str = ""     # limit to sub-directory, e.g. "docs/"
    file_types: list[str] = field(default_factory=list)   # empty = _DEFAULT_TYPES
    base_url: str = "https://api.github.com"              # GitHub Enterprise override


class GitHubConnector:
    def __init__(self, config: GitHubConfig):
        self.config = config
        self._types = (
            set(self.config.file_types) if self.config.file_types else _DEFAULT_TYPES
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _api(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"

    async def test_connection(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(self._api("user"), headers=self._headers())
                r.raise_for_status()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _get_tree(self, client: httpx.AsyncClient, repo: str) -> list[dict]:
        # Get default branch SHA
        r = await client.get(self._api(f"repos/{repo}/branches/{self.config.branch}"),
                             headers=self._headers())
        r.raise_for_status()
        sha = r.json()["commit"]["sha"]
        # Recursive tree
        r = await client.get(self._api(f"repos/{repo}/git/trees/{sha}"),
                             headers=self._headers(), params={"recursive": "1"})
        r.raise_for_status()
        items = r.json().get("tree", [])
        prefix = self.config.path_prefix.strip("/")
        result = []
        for item in items:
            if item.get("type") != "blob":
                continue
            path: str = item.get("path", "")
            if prefix and not path.startswith(prefix):
                continue
            ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext not in self._types:
                continue
            result.append(item)
        return result

    async def _get_content(self, client: httpx.AsyncClient, repo: str, path: str) -> str:
        r = await client.get(
            self._api(f"repos/{repo}/contents/{path}"),
            headers=self._headers(),
            params={"ref": self.config.branch},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return data.get("content", "")

    async def _collect(
        self, since_ts: float = 0.0
    ) -> tuple[list[ParsedDocument], dict]:
        docs: list[ParsedDocument] = []
        now = time.time()

        async with httpx.AsyncClient(timeout=30) as client:
            for repo in self.config.repos:
                try:
                    tree = await self._get_tree(client, repo)
                except Exception:
                    continue
                for item in tree:
                    path: str = item["path"]
                    title = path.rsplit("/", 1)[-1]
                    try:
                        content = await self._get_content(client, repo, path)
                    except Exception:
                        continue
                    if not content.strip():
                        continue
                    docs.append(ParsedDocument(
                        doc_id=_make_id(f"github:{repo}:{self.config.branch}:{path}"),
                        title=title,
                        source=f"https://github.com/{repo}/blob/{self.config.branch}/{path}",
                        content=content,
                        metadata={
                            "source_type": "github",
                            "repo": repo,
                            "branch": self.config.branch,
                            "path": path,
                        },
                    ))

        cursor = {"last_ts": now}
        return docs, cursor

    async def sync_documents(self) -> tuple[list[ParsedDocument], dict]:
        return await self._collect(0.0)

    async def sync_incremental(self, cursor: dict) -> tuple[list[ParsedDocument], dict]:
        # GitHub tree API doesn't expose per-file mtime efficiently;
        # fall back to full sync on small repos. For large repos with
        # many files, users should set a narrow path_prefix.
        return await self._collect(cursor.get("last_ts", 0.0))
