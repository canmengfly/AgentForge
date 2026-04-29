"""Tests for datasource CRUD API and document-platform connector logic."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── API CRUD ──────────────────────────────────────────────────────────────────

class TestDataSourceCRUD:

    def _create(self, client, ds_type, config, name=None):
        return client.post("/api/datasources", json={
            "name": name or f"test_{ds_type}",
            "type": ds_type,
            "config": config,
        })

    def test_create_feishu_datasource(self, as_admin):
        resp = self._create(as_admin, "feishu", {
            "app_id": "cli_xxx", "app_secret": "sec_yyy", "space_id": ""
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "feishu"
        assert data["status"] == "idle"
        # sensitive field masked
        assert data["config"].get("app_secret") == "***"

    def test_create_dingtalk_datasource(self, as_admin):
        resp = self._create(as_admin, "dingtalk", {
            "app_key": "dingkey", "app_secret": "dingsec"
        })
        assert resp.status_code == 200
        assert resp.json()["type"] == "dingtalk"

    def test_create_tencent_docs_datasource(self, as_admin):
        resp = self._create(as_admin, "tencent_docs", {
            "client_id": "cid", "client_secret": "csec",
            "access_token": "atk", "refresh_token": "rtk",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "tencent_docs"
        # all sensitive fields masked
        assert data["config"]["access_token"] == "***"
        assert data["config"]["refresh_token"] == "***"
        assert data["config"]["client_secret"] == "***"

    def test_response_has_required_fields(self, as_admin):
        resp = self._create(as_admin, "feishu", {"app_id": "a", "app_secret": "b"})
        data = resp.json()
        for field in ("id", "name", "type", "status", "doc_count", "created_at", "config"):
            assert field in data, f"missing field: {field}"

    def test_list_returns_only_own_sources(self, as_admin):
        self._create(as_admin, "feishu", {"app_id": "a", "app_secret": "b"}, name="listed_ds")
        resp = as_admin.get("/api/datasources")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert "listed_ds" in names

    def test_delete_datasource(self, as_admin):
        ds_id = self._create(as_admin, "dingtalk",
                             {"app_key": "k", "app_secret": "s"}).json()["id"]
        resp = as_admin.delete(f"/api/datasources/{ds_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        ids = [d["id"] for d in as_admin.get("/api/datasources").json()]
        assert ds_id not in ids

    def test_delete_nonexistent_returns_404(self, as_admin):
        assert as_admin.delete("/api/datasources/99999").status_code == 404

    def test_get_status(self, as_admin):
        ds_id = self._create(as_admin, "feishu",
                             {"app_id": "a", "app_secret": "b"}).json()["id"]
        resp = as_admin.get(f"/api/datasources/{ds_id}/status")
        assert resp.status_code == 200
        assert "status" in resp.json()

    def test_update_schedule_enable(self, as_admin):
        ds_id = self._create(as_admin, "feishu",
                             {"app_id": "a", "app_secret": "b"}).json()["id"]
        resp = as_admin.patch(f"/api/datasources/{ds_id}/schedule",
                              json={"sync_interval": 60})
        assert resp.status_code == 200
        assert resp.json()["sync_interval"] == 60

    def test_update_schedule_disable(self, as_admin):
        ds_id = self._create(as_admin, "feishu",
                             {"app_id": "a", "app_secret": "b"}).json()["id"]
        as_admin.patch(f"/api/datasources/{ds_id}/schedule", json={"sync_interval": 30})
        resp = as_admin.patch(f"/api/datasources/{ds_id}/schedule",
                              json={"sync_interval": None})
        assert resp.status_code == 200
        assert resp.json()["sync_interval"] is None

    def test_unauthenticated_list_returns_401(self, client):
        from tests.conftest import do_logout
        do_logout(client)
        assert client.get("/api/datasources").status_code == 401

    def test_test_connection_feishu(self, as_admin):
        ds_id = self._create(as_admin, "feishu",
                             {"app_id": "x", "app_secret": "y"}).json()["id"]
        with patch(
            "src.core.connectors.feishu_connector.FeishuConnector.test_connection",
            new=AsyncMock(return_value={"ok": True}),
        ):
            resp = as_admin.post(f"/api/datasources/{ds_id}/test")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── Feishu connector unit tests ───────────────────────────────────────────────

def _async_client_mock():
    """Return a mock that satisfies `async with httpx.AsyncClient(...) as c:`."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    return mock


class TestFeishuConnector:

    def _connector(self, space_id="sp1"):
        from src.core.connectors.feishu_connector import FeishuConfig, FeishuConnector
        return FeishuConnector(FeishuConfig(app_id="app1", app_secret="sec1", space_id=space_id))

    def test_sync_documents_returns_docs_and_cursor(self):
        c = self._connector()
        nodes = [
            {"obj_type": "docx", "obj_token": "t1", "title": "Doc One", "obj_edit_time": 1700000000},
            {"obj_type": "doc",  "obj_token": "t2", "title": "Doc Two", "obj_edit_time": 1700000001},
            {"obj_type": "folder", "obj_token": "f1", "title": "Folder"},  # skipped
        ]

        async def run():
            with patch.object(c, "_get_token", AsyncMock(return_value="tok")):
                with patch("httpx.AsyncClient", return_value=_async_client_mock()):
                    with patch.object(c, "_list_spaces", AsyncMock(return_value=["sp1"])):
                        with patch.object(c, "_list_nodes", AsyncMock(return_value=nodes)):
                            with patch.object(c, "_get_content", AsyncMock(return_value="Hello")):
                                return await c.sync_documents()

        docs, cursor = asyncio.run(run())
        assert len(docs) == 2
        assert docs[0].title == "Doc One"
        assert docs[0].metadata["source_type"] == "feishu"
        assert "last_mtime" in cursor

    def test_sync_skips_empty_content(self):
        c = self._connector()
        nodes = [{"obj_type": "docx", "obj_token": "t1", "title": "Empty", "obj_edit_time": 1700000000}]

        async def run():
            with patch.object(c, "_get_token", AsyncMock(return_value="tok")):
                with patch("httpx.AsyncClient", return_value=_async_client_mock()):
                    with patch.object(c, "_list_spaces", AsyncMock(return_value=["sp1"])):
                        with patch.object(c, "_list_nodes", AsyncMock(return_value=nodes)):
                            with patch.object(c, "_get_content", AsyncMock(return_value="   ")):
                                return await c.sync_documents()

        docs, _ = asyncio.run(run())
        assert docs == []

    def test_incremental_filters_old_nodes(self):
        c = self._connector()
        nodes = [
            {"obj_type": "docx", "obj_token": "new", "title": "New",
             "obj_edit_time": 1700000100},
            {"obj_type": "docx", "obj_token": "old", "title": "Old",
             "obj_edit_time": 1699000000},
        ]

        async def run():
            with patch.object(c, "_get_token", AsyncMock(return_value="tok")):
                with patch("httpx.AsyncClient", return_value=_async_client_mock()):
                    with patch.object(c, "_list_spaces", AsyncMock(return_value=["sp1"])):
                        with patch.object(c, "_list_nodes", AsyncMock(return_value=nodes)):
                            with patch.object(c, "_get_content", AsyncMock(return_value="content")):
                                return await c.sync_incremental({"last_mtime": 1699500000})

        docs, cursor = asyncio.run(run())
        assert len(docs) == 1
        assert docs[0].title == "New"
        assert cursor["last_mtime"] == 1700000100

    def test_doc_id_is_deterministic(self):
        c = self._connector()
        nodes = [{"obj_type": "docx", "obj_token": "stable", "title": "A",
                  "obj_edit_time": 1700000000}]

        async def run():
            with patch.object(c, "_get_token", AsyncMock(return_value="tok")):
                with patch("httpx.AsyncClient", return_value=_async_client_mock()):
                    with patch.object(c, "_list_spaces", AsyncMock(return_value=["sp1"])):
                        with patch.object(c, "_list_nodes", AsyncMock(return_value=nodes)):
                            with patch.object(c, "_get_content", AsyncMock(return_value="body")):
                                d1, _ = await c.sync_documents()
                                d2, _ = await c.sync_documents()
                                return d1, d2

        docs1, docs2 = asyncio.run(run())
        assert docs1[0].doc_id == docs2[0].doc_id


# ── DingTalk connector unit tests ─────────────────────────────────────────────

class TestDingTalkConnector:

    def _connector(self):
        from src.core.connectors.dingtalk_connector import DingTalkConfig, DingTalkConnector
        return DingTalkConnector(DingTalkConfig(app_key="k", app_secret="s", workspace_id="ws1"))

    def test_sync_documents_returns_docs(self):
        c = self._connector()
        nodes = [
            {"nodeType": "doc", "docId": "d1", "name": "Minutes", "modifyTime": 1700000000},
            {"nodeType": "folder", "docId": "f1", "name": "Folder"},  # skipped
        ]

        async def run():
            with patch.object(c, "_get_token", AsyncMock(return_value="tok")):
                with patch("httpx.AsyncClient", return_value=_async_client_mock()):
                    with patch.object(c, "_list_workspaces", AsyncMock(return_value=["ws1"])):
                        with patch.object(c, "_list_nodes", AsyncMock(return_value=nodes)):
                            with patch.object(c, "_get_content", AsyncMock(return_value="Meeting notes")):
                                return await c.sync_documents()

        docs, cursor = asyncio.run(run())
        assert len(docs) == 1
        assert docs[0].title == "Minutes"
        assert docs[0].metadata["source_type"] == "dingtalk"
        assert "last_mtime" in cursor

    def test_incremental_only_returns_new(self):
        c = self._connector()
        nodes = [
            {"nodeType": "doc", "docId": "n1", "name": "New", "modifyTime": 1700001000},
            {"nodeType": "doc", "docId": "o1", "name": "Old", "modifyTime": 1699000000},
        ]

        async def run():
            with patch.object(c, "_get_token", AsyncMock(return_value="tok")):
                with patch("httpx.AsyncClient", return_value=_async_client_mock()):
                    with patch.object(c, "_list_workspaces", AsyncMock(return_value=["ws1"])):
                        with patch.object(c, "_list_nodes", AsyncMock(return_value=nodes)):
                            with patch.object(c, "_get_content", AsyncMock(return_value="content")):
                                return await c.sync_incremental({"last_mtime": 1699500000})

        docs, _ = asyncio.run(run())
        assert len(docs) == 1
        assert docs[0].title == "New"

    def test_empty_nodes_returns_empty(self):
        c = self._connector()

        async def run():
            with patch.object(c, "_get_token", AsyncMock(return_value="tok")):
                with patch("httpx.AsyncClient", return_value=_async_client_mock()):
                    with patch.object(c, "_list_workspaces", AsyncMock(return_value=["ws1"])):
                        with patch.object(c, "_list_nodes", AsyncMock(return_value=[])):
                            return await c.sync_documents()

        docs, cursor = asyncio.run(run())
        assert docs == []
        assert "last_mtime" in cursor


# ── Tencent Docs connector unit tests ─────────────────────────────────────────

class TestTencentDocsConnector:

    def _connector(self):
        from src.core.connectors.tencent_docs_connector import TencentDocsConfig, TencentDocsConnector
        return TencentDocsConnector(TencentDocsConfig(
            client_id="cid", client_secret="csec",
            access_token="atk", refresh_token="rtk",
        ))

    def test_sync_documents_returns_exportable_types(self):
        c = self._connector()
        files = [
            {"id": "f1", "title": "Report",  "fileType": "document",     "updateTime": 1700000000},
            {"id": "f2", "title": "Sheet",   "fileType": "spreadsheet",  "updateTime": 1700000001},
            {"id": "f3", "title": "Slides",  "fileType": "presentation", "updateTime": 1700000002},
            {"id": "f4", "title": "Image",   "fileType": "image",        "updateTime": 1700000003},  # skipped
        ]

        async def run():
            with patch.object(c, "_list_files", AsyncMock(return_value=files)):
                with patch.object(c, "_export_content", AsyncMock(return_value="content")):
                    return await c.sync_documents()

        docs, cursor = asyncio.run(run())
        assert len(docs) == 3
        titles = {d.title for d in docs}
        assert "Report" in titles and "Sheet" in titles and "Slides" in titles
        assert "last_ts" in cursor

    def test_incremental_filters_old_files(self):
        c = self._connector()
        files = [
            {"id": "n1", "title": "New", "fileType": "document", "updateTime": 1700001000},
            {"id": "o1", "title": "Old", "fileType": "document", "updateTime": 1699000000},
        ]

        async def run():
            with patch.object(c, "_list_files", AsyncMock(return_value=files)):
                with patch.object(c, "_export_content", AsyncMock(return_value="content")):
                    return await c.sync_incremental({"last_ts": 1699500000})

        docs, _ = asyncio.run(run())
        assert len(docs) == 1
        assert docs[0].title == "New"

    def test_skips_files_with_empty_export(self):
        c = self._connector()
        files = [{"id": "f1", "title": "Blank", "fileType": "document", "updateTime": 1700000000}]

        async def run():
            with patch.object(c, "_list_files", AsyncMock(return_value=files)):
                with patch.object(c, "_export_content", AsyncMock(return_value="")):
                    return await c.sync_documents()

        docs, _ = asyncio.run(run())
        assert docs == []

    def test_source_url_contains_doc_id(self):
        c = self._connector()
        files = [{"id": "abc123", "title": "Doc", "fileType": "document", "updateTime": 1700000000}]

        async def run():
            with patch.object(c, "_list_files", AsyncMock(return_value=files)):
                with patch.object(c, "_export_content", AsyncMock(return_value="body")):
                    return await c.sync_documents()

        docs, _ = asyncio.run(run())
        assert "abc123" in docs[0].source
