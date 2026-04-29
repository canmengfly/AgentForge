"""Tests for 14 new connectors: Confluence, Notion, Yuque, GitHub, GitLab,
Oracle, SQL Server, TiDB, OceanBase, SharePoint, Google Drive,
Tencent COS, Huawei OBS, Snowflake."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _httpx_response(status: int = 200, json_data: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.content = text.encode()
    if status >= 400:
        from httpx import HTTPStatusError, Request, Response
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    else:
        resp.raise_for_status.return_value = None
    return resp


class FakeAsyncClient:
    """Minimal async context-manager HTTP client mock — picks the longest matching key."""
    def __init__(self, get_map: dict | None = None, post_map: dict | None = None):
        self._get = get_map or {}
        self._post = post_map or {}

    def _match(self, mapping: dict, url: str):
        best_key = max(
            (k for k in mapping if k in url),
            key=len,
            default=None,
        )
        return mapping[best_key] if best_key else _httpx_response(404)

    async def get(self, url, **kw):
        return self._match(self._get, url)

    async def post(self, url, **kw):
        return self._match(self._post, url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Confluence
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfluenceConnector:

    def _conn(self, **kw):
        from src.core.connectors.confluence_connector import ConfluenceConfig, ConfluenceConnector
        return ConfluenceConnector(ConfluenceConfig(
            base_url="https://test.atlassian.net",
            username="user@test.com",
            api_token="tok123",
            **kw,
        ))

    def test_api_url_cloud(self):
        c = self._conn()
        assert "/wiki/rest/api/" in c._api("space")

    def test_api_url_server(self):
        c = self._conn(is_cloud=False)
        assert "/wiki/" not in c._api("space")
        assert "/rest/api/" in c._api("space")

    def test_auth_header_is_basic(self):
        c = self._conn()
        h = c._auth_header()
        assert h["Authorization"].startswith("Basic ")

    def test_test_connection_ok(self):
        c = self._conn()
        ok_resp = _httpx_response(200, {"results": []})
        client = FakeAsyncClient(get_map={"space": ok_resp})
        with patch("httpx.AsyncClient", return_value=client):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_test_connection_fail(self):
        c = self._conn()
        client = FakeAsyncClient(get_map={"space": _httpx_response(401)})
        with patch("httpx.AsyncClient", return_value=client):
            result = run(c.test_connection())
        assert result["ok"] is False

    def test_page_to_doc_strips_html(self):
        c = self._conn()
        page = {
            "id": "123",
            "title": "My Page",
            "body": {"export_view": {"value": "<h1>Hello</h1><p>World</p>"}},
        }
        doc = c._page_to_doc(page, "ENG")
        assert doc is not None
        assert "Hello" in doc.content
        assert "<h1>" not in doc.content
        assert doc.metadata["source_type"] == "confluence"
        assert doc.metadata["space_key"] == "ENG"

    def test_page_to_doc_empty_body_returns_none(self):
        c = self._conn()
        page = {"id": "1", "title": "Empty", "body": {"export_view": {"value": "   "}}}
        assert c._page_to_doc(page, "ENG") is None

    def test_sync_with_space_keys(self):
        c = self._conn(space_keys=["ENG"])
        space_resp = _httpx_response(200, {"results": [], "_links": {}})
        pages_resp = _httpx_response(200, {"results": [
            {"id": "1", "title": "Doc", "body": {"export_view": {"value": "<p>Content</p>"}},
             "history": {"lastUpdated": {"when": "2024-01-02T00:00:00Z"}}}
        ], "_links": {}})
        client = FakeAsyncClient(get_map={"space": space_resp, "content": pages_resp})
        with patch("httpx.AsyncClient", return_value=client):
            docs, cursor = run(c.sync_documents())
        assert len(docs) == 1
        assert "last_iso" in cursor

    def test_incremental_filters_old_pages(self):
        c = self._conn(space_keys=["ENG"])
        pages_resp = _httpx_response(200, {"results": [
            {"id": "1", "title": "Old", "body": {"export_view": {"value": "<p>x</p>"}},
             "history": {"lastUpdated": {"when": "2023-01-01T00:00:00Z"}}}
        ], "_links": {}})
        client = FakeAsyncClient(get_map={"content": pages_resp})
        with patch("httpx.AsyncClient", return_value=client):
            # since_iso is 2024, page is 2023 → should be filtered
            docs, _ = run(c.sync_incremental({"last_iso": "2024-01-01T00:00:00Z"}))
        assert docs == []


# ═══════════════════════════════════════════════════════════════════════════════
# Notion
# ═══════════════════════════════════════════════════════════════════════════════

class TestNotionConnector:

    def _conn(self, **kw):
        from src.core.connectors.notion_connector import NotionConfig, NotionConnector
        return NotionConnector(NotionConfig(token="secret_tok", **kw))

    def test_headers_include_version(self):
        c = self._conn()
        h = c._headers()
        assert "Notion-Version" in h
        assert h["Authorization"] == "Bearer secret_tok"

    def test_test_connection_ok(self):
        c = self._conn()
        ok = _httpx_response(200, {"object": "user"})
        client = FakeAsyncClient(get_map={"users/me": ok})
        with patch("httpx.AsyncClient", return_value=client):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_rich_text_extraction(self):
        c = self._conn()
        rt = [{"plain_text": "Hello "}, {"plain_text": "World"}]
        assert c._rich_text(rt) == "Hello World"

    def test_block_text_paragraph(self):
        c = self._conn()
        block = {
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": "My paragraph"}]},
        }
        assert c._block_text(block) == "My paragraph"

    def test_page_title_extraction(self):
        c = self._conn()
        page = {
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "My Page Title"}],
                }
            }
        }
        assert c._page_title(page) == "My Page Title"

    def test_page_title_fallback(self):
        c = self._conn()
        assert c._page_title({}) == "Untitled"

    def test_sync_documents_with_specific_pages(self):
        c = self._conn(page_ids=["page-id-123"])

        page_meta = {"id": "page-id-123", "object": "page",
                     "properties": {"Name": {"type": "title", "title": [{"plain_text": "Test"}]}}}
        blocks = {"results": [
            {"id": "b1", "type": "paragraph",
             "paragraph": {"rich_text": [{"plain_text": "Hello Notion"}]},
             "has_children": False}
        ], "has_more": False}

        get_map = {
            "pages/page-id-123": _httpx_response(200, page_meta),
            "blocks/page-id-123/children": _httpx_response(200, blocks),
        }
        client = FakeAsyncClient(get_map=get_map)
        with patch("httpx.AsyncClient", return_value=client):
            docs, cursor = run(c.sync_documents())
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "notion"
        assert "Hello Notion" in docs[0].content


# ═══════════════════════════════════════════════════════════════════════════════
# Yuque
# ═══════════════════════════════════════════════════════════════════════════════

class TestYuqueConnector:

    def _conn(self, **kw):
        from src.core.connectors.yuque_connector import YuqueConfig, YuqueConnector
        return YuqueConnector(YuqueConfig(token="yuque_tok", **kw))

    def test_headers(self):
        c = self._conn()
        assert c._headers()["X-Auth-Token"] == "yuque_tok"

    def test_api_url(self):
        c = self._conn()
        assert "api/v2/user" in c._api("user")

    def test_test_connection_ok(self):
        c = self._conn()
        ok = _httpx_response(200, {"data": {"id": 1}})
        client = FakeAsyncClient(get_map={"user": ok})
        with patch("httpx.AsyncClient", return_value=client):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_namespace_specified(self):
        c = self._conn(namespace="myteam/docs")
        repos_resp = _httpx_response(200, {"data": []})
        docs_resp = _httpx_response(200, {"data": [
            {"id": 1, "slug": "intro", "title": "Intro", "updated_at": "2024-01-01T00:00:00Z"}
        ]})
        doc_resp = _httpx_response(200, {"data": {"body_html": "<p>Welcome</p>", "body": ""}})
        get_map = {
            "mine/repos": repos_resp,
            "repos/myteam/docs/docs": docs_resp,
            "repos/myteam/docs/docs/intro": doc_resp,
        }
        client = FakeAsyncClient(get_map=get_map)
        with patch("httpx.AsyncClient", return_value=client):
            docs, cursor = run(c.sync_documents())
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "yuque"
        assert "Welcome" in docs[0].content

    def test_private_deployment_base_url(self):
        c = self._conn(base_url="https://yuque.company.com")
        assert "yuque.company.com" in c._api("user")

    def test_incremental_skips_old(self):
        c = self._conn(namespace="team/repo")
        docs_resp = _httpx_response(200, {"data": [
            {"id": 1, "slug": "old", "title": "Old",
             "updated_at": "2022-01-01T00:00:00Z"}
        ]})
        doc_resp = _httpx_response(200, {"data": {"body_html": "<p>x</p>"}})
        client = FakeAsyncClient(get_map={
            "repos/team/repo/docs": docs_resp,
            "repos/team/repo/docs/old": doc_resp,
        })
        with patch("httpx.AsyncClient", return_value=client):
            docs, _ = run(c.sync_incremental({"last_ts": 1_700_000_000.0}))
        assert docs == []


# ═══════════════════════════════════════════════════════════════════════════════
# GitHub
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitHubConnector:

    def _conn(self, **kw):
        from src.core.connectors.github_connector import GitHubConfig, GitHubConnector
        return GitHubConnector(GitHubConfig(token="ghp_tok", repos=["owner/repo"], **kw))

    def test_headers(self):
        c = self._conn()
        assert c._headers()["Authorization"] == "Bearer ghp_tok"

    def test_test_connection_ok(self):
        c = self._conn()
        ok = _httpx_response(200, {"login": "owner"})
        client = FakeAsyncClient(get_map={"user": ok})
        with patch("httpx.AsyncClient", return_value=client):
            assert run(c.test_connection())["ok"] is True

    def test_sync_fetches_markdown_files(self):
        c = self._conn()
        branch_resp = _httpx_response(200, {"commit": {"sha": "abc123"}})
        tree_resp = _httpx_response(200, {"tree": [
            {"type": "blob", "path": "README.md", "sha": "d1"},
            {"type": "blob", "path": "src/main.py", "sha": "d2"},  # filtered out
        ]})
        import base64
        content_resp = _httpx_response(200, {
            "content": base64.b64encode(b"# Hello").decode(),
            "encoding": "base64",
        })
        get_map = {
            "branches/main": branch_resp,
            "git/trees/abc123": tree_resp,
            "contents/README.md": content_resp,
        }
        client = FakeAsyncClient(get_map=get_map)
        with patch("httpx.AsyncClient", return_value=client):
            docs, _ = run(c.sync_documents())
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "github"
        assert "Hello" in docs[0].content

    def test_path_prefix_filter(self):
        c = self._conn(path_prefix="docs/")
        branch_resp = _httpx_response(200, {"commit": {"sha": "abc"}})
        tree_resp = _httpx_response(200, {"tree": [
            {"type": "blob", "path": "docs/guide.md", "sha": "d1"},
            {"type": "blob", "path": "README.md", "sha": "d2"},  # excluded
        ]})
        import base64
        content_resp = _httpx_response(200, {
            "content": base64.b64encode(b"Guide content").decode(),
            "encoding": "base64",
        })
        get_map = {
            "branches/main": branch_resp,
            "git/trees/abc": tree_resp,
            "contents/docs/guide.md": content_resp,
        }
        client = FakeAsyncClient(get_map=get_map)
        with patch("httpx.AsyncClient", return_value=client):
            docs, _ = run(c.sync_documents())
        assert len(docs) == 1
        assert docs[0].metadata["path"] == "docs/guide.md"

    def test_enterprise_base_url(self):
        c = self._conn(base_url="https://github.company.com/api/v3")
        assert "github.company.com" in c._api("user")

    def test_custom_file_types(self):
        c = self._conn(file_types=[".rst"])
        assert ".rst" in c._types
        assert ".md" not in c._types


# ═══════════════════════════════════════════════════════════════════════════════
# GitLab
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitLabConnector:

    def _conn(self, **kw):
        from src.core.connectors.gitlab_connector import GitLabConfig, GitLabConnector
        return GitLabConnector(GitLabConfig(
            token="glpat_tok", projects=["group/project"], **kw
        ))

    def test_headers(self):
        c = self._conn()
        assert c._headers()["PRIVATE-TOKEN"] == "glpat_tok"

    def test_test_connection_ok(self):
        c = self._conn()
        ok = _httpx_response(200, {"id": 1})
        client = FakeAsyncClient(get_map={"user": ok})
        with patch("httpx.AsyncClient", return_value=client):
            assert run(c.test_connection())["ok"] is True

    def test_sync_fetches_md_files(self):
        c = self._conn()
        tree_resp = _httpx_response(200, [
            {"type": "blob", "path": "README.md"},
            {"type": "blob", "path": "Makefile"},  # excluded
        ])
        content_resp = _httpx_response(200, text="# GitLab Doc\nContent here")
        get_map = {
            "repository/tree": tree_resp,
            "repository/files": content_resp,
        }
        client = FakeAsyncClient(get_map=get_map)
        with patch("httpx.AsyncClient", return_value=client):
            docs, _ = run(c.sync_documents())
        assert any(d.metadata["source_type"] == "gitlab" for d in docs)

    def test_private_gitlab_url(self):
        c = self._conn(base_url="https://gitlab.company.com")
        assert "gitlab.company.com" in c._api("projects")

    def test_project_id_encoded(self):
        from src.core.connectors.gitlab_connector import GitLabConfig, GitLabConnector
        cfg = GitLabConfig(token="t", projects=["my group/my project"])
        c = GitLabConnector(cfg)
        encoded = c._encode("my group/my project")
        assert " " not in encoded


# ═══════════════════════════════════════════════════════════════════════════════
# Oracle
# ═══════════════════════════════════════════════════════════════════════════════

class TestOracleConnector:

    def _conn(self, **kw):
        from src.core.connectors.oracle_connector import OracleConfig, OracleConnector
        return OracleConnector(OracleConfig(
            host="ora-host", service_name="ORCL",
            username="scott", password="tiger", **kw
        ))

    def test_test_connection_ok(self):
        c = self._conn()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        with patch.object(c, "_make_connection", return_value=mock_conn):
            result = run(c.test_connection())
        assert result["ok"] is True
        mock_cur.execute.assert_called_once()

    def test_test_connection_fail(self):
        c = self._conn()
        with patch.object(c, "_make_connection", side_effect=Exception("ORA-12541")):
            result = run(c.test_connection())
        assert result["ok"] is False
        assert "ORA-12541" in result["error"]

    def test_row_to_doc(self):
        c = self._conn()
        record = {"ID": 1, "NAME": "Alice", "DEPT": "Engineering"}
        doc = c._row_to_doc(record, "EMPLOYEES", 0)
        assert doc is not None
        assert doc.metadata["source_type"] == "oracle"
        assert "EMPLOYEES" in doc.content
        assert "Alice" in doc.content

    def test_empty_row_skipped(self):
        c = self._conn()
        assert c._row_to_doc({}, "T", 0) is None

    def test_sync_documents(self):
        c = self._conn(tables=["EMPLOYEES"])
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchall.return_value = [(1, "Alice"), (2, "Bob")]
        mock_cur.description = [("ID", None), ("NAME", None)]
        mock_cur.execute.return_value = None
        with patch.object(c, "_make_connection", return_value=mock_conn):
            docs, cursor = run(c.sync_documents())
        assert len(docs) == 2
        assert "last_ts" in cursor

    def test_oracledb_import_error(self):
        c = self._conn()
        with patch.dict("sys.modules", {"oracledb": None}):
            with pytest.raises(RuntimeError, match="oracledb"):
                c._make_connection()

    def test_default_port_1521(self):
        c = self._conn()
        assert c.config.port == 1521


# ═══════════════════════════════════════════════════════════════════════════════
# SQL Server
# ═══════════════════════════════════════════════════════════════════════════════

class TestSQLServerConnector:

    def _conn(self, **kw):
        from src.core.connectors.sqlserver_connector import SQLServerConfig, SQLServerConnector
        return SQLServerConnector(SQLServerConfig(
            host="mssql-host", database="AdventureWorks",
            username="sa", password="Pass@word", **kw
        ))

    def test_default_port(self):
        c = self._conn()
        assert c.config.port == 1433

    def test_test_connection_ok(self):
        c = self._conn()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        with patch.object(c, "_make_connection", return_value=mock_conn):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_row_to_doc(self):
        c = self._conn()
        record = {"id": 1, "CustomerName": "Acme", "Country": "US"}
        doc = c._row_to_doc(record, "Customers", 0)
        assert doc is not None
        assert doc.metadata["source_type"] == "sqlserver"
        assert "Acme" in doc.content

    def test_sync_with_tables(self):
        c = self._conn(tables=["Customers"])
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchall.return_value = [{"id": 1, "name": "Acme"}]
        with patch.object(c, "_make_connection", return_value=mock_conn):
            docs, cursor = run(c.sync_documents())
        assert "last_ts" in cursor

    def test_pymssql_import_error(self):
        c = self._conn()
        with patch.dict("sys.modules", {"pymssql": None}):
            with pytest.raises(RuntimeError, match="pymssql"):
                c._make_connection()


# ═══════════════════════════════════════════════════════════════════════════════
# TiDB & OceanBase (thin wrappers)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTiDBConnector:

    def _conn(self, **kw):
        from src.core.connectors.tidb_connector import TiDBConfig, TiDBConnector
        return TiDBConnector(TiDBConfig(
            host="tidb-host", database="test", username="root", password="", **kw
        ))

    def test_default_port_4000(self):
        c = self._conn()
        assert c._inner.config.port == 4000

    def test_source_type_overridden(self):
        c = self._conn()
        mock_docs = [MagicMock(metadata={"source_type": "sql"})]

        async def _fake():
            return mock_docs, {}
        with patch.object(c._inner, "sync_documents", side_effect=_fake):
            docs, _ = run(c.sync_documents())
        assert all(d.metadata["source_type"] == "tidb" for d in docs)

    def test_incremental_source_type(self):
        c = self._conn()
        mock_docs = [MagicMock(metadata={"source_type": "sql"})]

        async def _fake(cursor):
            return mock_docs, {}
        with patch.object(c._inner, "sync_incremental", side_effect=_fake):
            docs, _ = run(c.sync_incremental({}))
        assert all(d.metadata["source_type"] == "tidb" for d in docs)


class TestOceanBaseConnector:

    def _conn(self, **kw):
        from src.core.connectors.oceanbase_connector import OceanBaseConfig, OceanBaseConnector
        return OceanBaseConnector(OceanBaseConfig(
            host="ob-host", database="test", username="root", password="", **kw
        ))

    def test_default_port_2881(self):
        c = self._conn()
        assert c._inner.config.port == 2881

    def test_source_type_overridden(self):
        c = self._conn()
        mock_docs = [MagicMock(metadata={"source_type": "sql"})]

        async def _fake():
            return mock_docs, {}
        with patch.object(c._inner, "sync_documents", side_effect=_fake):
            docs, _ = run(c.sync_documents())
        assert all(d.metadata["source_type"] == "oceanbase" for d in docs)


# ═══════════════════════════════════════════════════════════════════════════════
# SharePoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharePointConnector:

    def _conn(self, **kw):
        from src.core.connectors.sharepoint_connector import SharePointConfig, SharePointConnector
        return SharePointConnector(SharePointConfig(
            tenant_id="t123",
            client_id="c123",
            client_secret="s123",
            site_url="https://company.sharepoint.com/sites/wiki",
            **kw,
        ))

    def test_test_connection_ok(self):
        c = self._conn()
        token_resp = _httpx_response(200, {"access_token": "tok", "expires_in": 3600})
        site_resp = _httpx_response(200, {"id": "site-id-1"})

        async def fake_post(url, **kw):
            return token_resp

        async def fake_get(url, **kw):
            if "login.microsoftonline" in url:
                return token_resp
            return site_resp

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=token_resp)
        mock_client.get = AsyncMock(return_value=site_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_test_connection_fail(self):
        c = self._conn()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=Exception("auth failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = run(c.test_connection())
        assert result["ok"] is False

    def test_source_type_metadata(self):
        c = self._conn()
        # Verify config stored correctly
        assert c.config.tenant_id == "t123"
        assert c.config.site_url == "https://company.sharepoint.com/sites/wiki"


# ═══════════════════════════════════════════════════════════════════════════════
# Google Drive
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoogleDriveConnector:

    def _conn(self, **kw):
        from src.core.connectors.google_drive_connector import GoogleDriveConfig, GoogleDriveConnector
        creds = json.dumps({"type": "service_account", "project_id": "test"})
        return GoogleDriveConnector(GoogleDriveConfig(credentials_json=creds, **kw))

    def test_import_error(self):
        c = self._conn()
        with patch.dict("sys.modules", {
            "google.oauth2": None,
            "google.oauth2.service_account": None,
            "googleapiclient": None,
            "googleapiclient.discovery": None,
        }):
            with pytest.raises(RuntimeError, match="google-api-python-client"):
                c._build_service()

    def test_test_connection_ok(self):
        c = self._conn()
        mock_svc = MagicMock()
        mock_svc.files.return_value.list.return_value.execute.return_value = {"files": []}
        with patch.object(c, "_build_service", return_value=mock_svc):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_test_connection_fail(self):
        c = self._conn()
        with patch.object(c, "_build_service", side_effect=Exception("credentials error")):
            result = run(c.test_connection())
        assert result["ok"] is False

    def test_list_files_with_folder(self):
        c = self._conn(folder_id="folder123")
        mock_svc = MagicMock()
        mock_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "f1", "name": "doc.txt", "mimeType": "text/plain", "modifiedTime": "2024-01-01T00:00:00Z"}
            ]
        }
        files = c._list_files(mock_svc, None)
        call_kwargs = mock_svc.files.return_value.list.call_args[1]
        assert "folder123" in call_kwargs["q"]

    def test_sync_creates_docs(self):
        c = self._conn()
        mock_svc = MagicMock()
        mock_svc.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "f1", "name": "report.txt",
                 "mimeType": "text/plain", "modifiedTime": "2024-01-01T00:00:00Z"}
            ]
        }
        mock_req = MagicMock()
        mock_svc.files.return_value.get_media.return_value = mock_req

        mock_dl = MagicMock()
        mock_dl.next_chunk.return_value = (None, True)
        mock_http_module = MagicMock()
        mock_http_module.MediaIoBaseDownload.return_value = mock_dl

        with patch.dict("sys.modules", {
            "googleapiclient": MagicMock(),
            "googleapiclient.http": mock_http_module,
        }):
            with patch.object(c, "_build_service", return_value=mock_svc):
                docs, cursor = run(c.sync_documents())
        assert "last_iso" in cursor


# ═══════════════════════════════════════════════════════════════════════════════
# Tencent COS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTencentCOSConnector:

    def _conn(self, **kw):
        from src.core.connectors.tencent_cos_connector import TencentCOSConfig, TencentCOSConnector
        return TencentCOSConnector(TencentCOSConfig(
            region="ap-beijing", secret_id="AKIDxxx",
            secret_key="secret", bucket="mybucket-1234567890", **kw
        ))

    def test_import_error(self):
        c = self._conn()
        with patch.dict("sys.modules", {"qcloud_cos": None}):
            with pytest.raises(RuntimeError, match="cos-python-sdk-v5"):
                c._make_client()

    def test_test_connection_ok(self):
        c = self._conn()
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}
        with patch.object(c, "_make_client", return_value=mock_client):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_test_connection_fail(self):
        c = self._conn()
        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = Exception("NoSuchBucket")
        with patch.object(c, "_make_client", return_value=mock_client):
            result = run(c.test_connection())
        assert result["ok"] is False

    def test_sync_empty_bucket(self):
        c = self._conn()
        mock_client = MagicMock()
        mock_client.list_objects.return_value = {
            "Contents": [], "IsTruncated": "false"
        }
        with patch.object(c, "_make_client", return_value=mock_client):
            docs, cursor = run(c.sync_documents())
        assert docs == []
        assert "last_mtime" in cursor

    def test_sync_filters_unsupported(self):
        import datetime, time
        now_str = datetime.datetime.utcnow().isoformat() + "Z"
        c = self._conn()
        mock_client = MagicMock()
        mock_client.list_objects.return_value = {
            "Contents": [
                {"Key": "script.sh", "LastModified": now_str},
                {"Key": "readme.txt", "LastModified": now_str},
            ],
            "IsTruncated": "false",
        }
        mock_client.get_object.return_value = {
            "Body": MagicMock(get_raw_stream=lambda: MagicMock(read=lambda: b"text"))
        }
        with patch.object(c, "_make_client", return_value=mock_client):
            docs, _ = run(c.sync_documents())
        names = [d.source.split("/")[-1] for d in docs]
        assert "script.sh" not in names

    def test_source_type_metadata(self):
        import datetime
        now_str = datetime.datetime.utcnow().isoformat() + "Z"
        c = self._conn()
        mock_client = MagicMock()
        mock_client.list_objects.return_value = {
            "Contents": [{"Key": "docs/guide.txt", "LastModified": now_str}],
            "IsTruncated": "false",
        }
        mock_client.get_object.return_value = {
            "Body": MagicMock(get_raw_stream=lambda: MagicMock(read=lambda: b"guide content"))
        }
        with patch.object(c, "_make_client", return_value=mock_client):
            docs, _ = run(c.sync_documents())
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "tencent_cos"
        assert docs[0].metadata["cos_bucket"] == "mybucket-1234567890"


# ═══════════════════════════════════════════════════════════════════════════════
# Huawei OBS
# ═══════════════════════════════════════════════════════════════════════════════

class TestHuaweiOBSConnector:

    def _conn(self, **kw):
        from src.core.connectors.huawei_obs_connector import HuaweiOBSConfig, HuaweiOBSConnector
        return HuaweiOBSConnector(HuaweiOBSConfig(
            access_key_id="AK", secret_access_key="SK",
            endpoint="https://obs.cn-north-4.myhuaweicloud.com",
            bucket="test-bucket", **kw
        ))

    def test_import_error(self):
        c = self._conn()
        with patch.dict("sys.modules", {"obs": None}):
            with pytest.raises(RuntimeError, match="esdk-obs-python"):
                c._make_client()

    def test_test_connection_ok(self):
        c = self._conn()
        mock_client = MagicMock()
        mock_client.headBucket.return_value = MagicMock(status=200)
        with patch.object(c, "_make_client", return_value=mock_client):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_test_connection_fail(self):
        c = self._conn()
        mock_client = MagicMock()
        mock_client.headBucket.side_effect = Exception("connection error")
        with patch.object(c, "_make_client", return_value=mock_client):
            result = run(c.test_connection())
        assert result["ok"] is False

    def test_sync_empty(self):
        c = self._conn()
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.contents = []
        mock_body.is_truncated = False
        mock_client.listObjects.return_value = MagicMock(status=200, body=mock_body)
        with patch.object(c, "_make_client", return_value=mock_client):
            docs, cursor = run(c.sync_documents())
        assert docs == []
        assert "last_mtime" in cursor

    def test_source_type_metadata(self):
        import datetime
        now_str = datetime.datetime.utcnow().isoformat() + "Z"
        c = self._conn()
        mock_client = MagicMock()
        obj = MagicMock()
        obj.key = "notes/readme.txt"
        obj.lastModified = now_str
        mock_body = MagicMock()
        mock_body.contents = [obj]
        mock_body.is_truncated = False
        mock_client.listObjects.return_value = MagicMock(status=200, body=mock_body)
        get_resp = MagicMock()
        get_resp.status = 200
        get_resp.body.buffer = b"readme content"
        mock_client.getObject.return_value = get_resp
        with patch.object(c, "_make_client", return_value=mock_client):
            docs, _ = run(c.sync_documents())
        assert len(docs) == 1
        assert docs[0].metadata["source_type"] == "huawei_obs"
        assert docs[0].metadata["obs_bucket"] == "test-bucket"


# ═══════════════════════════════════════════════════════════════════════════════
# Snowflake
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnowflakeConnector:

    def _conn(self, **kw):
        from src.core.connectors.snowflake_connector import SnowflakeConfig, SnowflakeConnector
        return SnowflakeConnector(SnowflakeConfig(
            account="myorg-myaccount", user="MYUSER",
            password="pass", database="MY_DB", **kw
        ))

    def test_import_error(self):
        c = self._conn()
        with patch.dict("sys.modules", {"snowflake": None, "snowflake.sqlalchemy": None}):
            with pytest.raises(RuntimeError, match="snowflake-sqlalchemy"):
                c._make_engine()

    def test_test_connection_ok(self):
        c = self._conn()
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        with patch.object(c, "_make_engine", return_value=mock_engine):
            result = run(c.test_connection())
        assert result["ok"] is True

    def test_row_to_doc(self):
        c = self._conn()
        record = {"ID": "1", "PRODUCT": "Widget", "PRICE": 9.99}
        doc = c._row_to_doc(record, "PRODUCTS", 0)
        assert doc is not None
        assert doc.metadata["source_type"] == "snowflake"
        assert doc.metadata["database"] == "MY_DB"
        assert doc.metadata["schema"] == "PUBLIC"
        assert "Widget" in doc.content

    def test_default_schema_public(self):
        c = self._conn()
        assert c.config.schema == "PUBLIC"

    def test_sync_documents(self):
        c = self._conn(tables=["ORDERS"])
        mock_engine = MagicMock()
        mock_conn_ctx = MagicMock()
        mock_conn_ctx.__enter__ = MagicMock(return_value=mock_conn_ctx)
        mock_conn_ctx.__exit__ = MagicMock(return_value=False)
        mock_result = MagicMock()
        mock_result.keys.return_value = ["ID", "PRODUCT"]
        mock_result.__iter__ = MagicMock(return_value=iter([("1", "Widget"), ("2", "Gadget")]))
        mock_conn_ctx.execute.return_value = mock_result
        mock_engine.connect.return_value = mock_conn_ctx
        with patch.object(c, "_make_engine", return_value=mock_engine):
            docs, cursor = run(c.sync_documents())
        assert "last_ts" in cursor


# ═══════════════════════════════════════════════════════════════════════════════
# DataSourceType enum completeness
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataSourceTypeEnumExtended:
    def test_all_new_types_present(self):
        from src.core.models import DataSourceType
        new_types = [
            "tencent_cos", "huawei_obs",
            "oracle", "sqlserver", "tidb", "oceanbase", "snowflake",
            "confluence", "notion", "yuque",
            "github", "gitlab",
            "sharepoint", "google_drive",
        ]
        for t in new_types:
            assert hasattr(DataSourceType, t), f"DataSourceType missing: {t}"


# ═══════════════════════════════════════════════════════════════════════════════
# API CRUD for new types
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtendedDatasourceAPI:

    def _create(self, client, ds_type: str, config: dict, name: str | None = None):
        return client.post("/api/datasources", json={
            "name": name or f"Test {ds_type}",
            "type": ds_type,
            "config": config,
        })

    def test_create_confluence(self, as_user):
        resp = self._create(as_user, "confluence", {
            "base_url": "https://test.atlassian.net",
            "username": "u@test.com",
            "api_token": "tok123",
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["api_token"] == "***"

    def test_create_notion(self, as_user):
        resp = self._create(as_user, "notion", {"token": "secret_tok"})
        assert resp.status_code == 200
        assert resp.json()["config"]["token"] == "***"

    def test_create_yuque(self, as_user):
        resp = self._create(as_user, "yuque", {
            "token": "yuque_tok", "namespace": "team/docs"
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["token"] == "***"

    def test_create_github(self, as_user):
        resp = self._create(as_user, "github", {
            "token": "ghp_tok", "repos": "owner/repo"
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["token"] == "***"

    def test_create_gitlab(self, as_user):
        resp = self._create(as_user, "gitlab", {
            "token": "glpat_tok", "projects": "group/project"
        })
        assert resp.status_code == 200

    def test_create_oracle(self, as_user):
        resp = self._create(as_user, "oracle", {
            "host": "ora-host", "service_name": "ORCL",
            "username": "scott", "password": "tiger"
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["password"] == "***"

    def test_create_sqlserver(self, as_user):
        resp = self._create(as_user, "sqlserver", {
            "host": "mssql-host", "database": "DB",
            "username": "sa", "password": "pass"
        })
        assert resp.status_code == 200

    def test_create_tidb(self, as_user):
        resp = self._create(as_user, "tidb", {
            "host": "tidb-host", "database": "test",
            "username": "root", "password": ""
        })
        assert resp.status_code == 200
        assert resp.json()["type"] == "tidb"

    def test_create_oceanbase(self, as_user):
        resp = self._create(as_user, "oceanbase", {
            "host": "ob-host", "database": "test",
            "username": "root", "password": ""
        })
        assert resp.status_code == 200

    def test_create_snowflake(self, as_user):
        resp = self._create(as_user, "snowflake", {
            "account": "myorg-myaccount", "user": "MYUSER",
            "password": "pass", "database": "MY_DB"
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["password"] == "***"

    def test_create_tencent_cos(self, as_user):
        resp = self._create(as_user, "tencent_cos", {
            "region": "ap-beijing", "secret_id": "AKIDxxx",
            "secret_key": "secret", "bucket": "mybucket-1234567890"
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["secret_key"] == "***"

    def test_create_huawei_obs(self, as_user):
        resp = self._create(as_user, "huawei_obs", {
            "access_key_id": "AK", "secret_access_key": "SK",
            "endpoint": "https://obs.cn-north-4.myhuaweicloud.com",
            "bucket": "test-bucket"
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["secret_access_key"] == "***"

    def test_create_sharepoint(self, as_user):
        resp = self._create(as_user, "sharepoint", {
            "tenant_id": "t123", "client_id": "c123",
            "client_secret": "s123",
            "site_url": "https://company.sharepoint.com/sites/wiki"
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["client_secret"] == "***"

    def test_create_google_drive(self, as_user):
        resp = self._create(as_user, "google_drive", {
            "credentials_json": '{"type":"service_account"}'
        })
        assert resp.status_code == 200
        assert resp.json()["config"]["credentials_json"] == "***"

    def test_all_new_types_listable(self, as_user):
        types = ["confluence", "notion", "github", "tidb", "snowflake", "tencent_cos"]
        configs = {
            "confluence": {"base_url": "https://x.atlassian.net", "username": "u", "api_token": "t"},
            "notion": {"token": "t"},
            "github": {"token": "t", "repos": "o/r"},
            "tidb": {"host": "h", "database": "d", "username": "u", "password": "p"},
            "snowflake": {"account": "a", "user": "u", "password": "p", "database": "d"},
            "tencent_cos": {"region": "r", "secret_id": "i", "secret_key": "k", "bucket": "b"},
        }
        for t in types:
            self._create(as_user, t, configs[t])

        resp = as_user.get("/api/datasources")
        found = {ds["type"] for ds in resp.json()}
        for t in types:
            assert t in found, f"type {t} not found in list"

    def test_delete_works(self, as_user):
        resp = self._create(as_user, "notion", {"token": "t"})
        ds_id = resp.json()["id"]
        del_resp = as_user.delete(f"/api/datasources/{ds_id}")
        assert del_resp.json()["deleted"] is True
