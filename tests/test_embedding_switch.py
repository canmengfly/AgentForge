"""Tests for the embedding model management admin API."""
import pytest
from unittest.mock import patch, MagicMock
from src.core.config import SUPPORTED_MODELS


@pytest.fixture(autouse=True)
def reset_reindex_state():
    """Reset the in-memory reindex state before each test."""
    import src.api.routes.admin as admin_module
    admin_module._reindex.update(running=False, phase=None, total=0, done=0, error=None)
    yield
    admin_module._reindex.update(running=False, phase=None, total=0, done=0, error=None)


class TestGetEmbeddingInfo:

    def test_returns_current_model(self, as_admin):
        resp = as_admin.get("/api/admin/embedding")
        assert resp.status_code == 200
        data = resp.json()
        assert "current" in data
        assert "name" in data["current"]

    def test_lists_supported_models(self, as_admin):
        resp = as_admin.get("/api/admin/embedding")
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) == len(SUPPORTED_MODELS)
        names = [m["name"] for m in data["models"]]
        assert "all-MiniLM-L6-v2" in names

    def test_model_has_required_fields(self, as_admin):
        resp = as_admin.get("/api/admin/embedding")
        for m in resp.json()["models"]:
            for field in ("name", "dim", "lang", "size_mb", "desc"):
                assert field in m, f"model missing field: {field}"

    def test_returns_total_chunks(self, as_admin):
        resp = as_admin.get("/api/admin/embedding")
        data = resp.json()
        assert "total_chunks" in data
        assert isinstance(data["total_chunks"], int)

    def test_returns_reindex_state(self, as_admin):
        resp = as_admin.get("/api/admin/embedding")
        data = resp.json()
        assert "reindex" in data
        assert "running" in data["reindex"]

    def test_requires_admin(self, as_user):
        resp = as_user.get("/api/admin/embedding")
        assert resp.status_code == 403


class TestSwitchEmbeddingModel:

    def test_unsupported_model_returns_400(self, as_admin):
        resp = as_admin.post("/api/admin/embedding/switch", json={
            "model_name": "nonexistent/fake-model",
            "reindex": False,
        })
        assert resp.status_code == 400

    def test_switch_valid_model_no_reindex(self, as_admin):
        target = SUPPORTED_MODELS[1]["name"]  # second model in the list
        with patch("src.core.embeddings.switch_model"):
            resp = as_admin.post("/api/admin/embedding/switch", json={
                "model_name": target,
                "reindex": False,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["model"]["name"] == target
        assert data["reindexing"] is False

    def test_switch_persists_to_db(self, as_admin, app):
        """After switching, the active model name should be stored in SystemConfig."""
        from fastapi.testclient import TestClient
        target = SUPPORTED_MODELS[1]["name"]
        with patch("src.core.embeddings.switch_model"):
            as_admin.post("/api/admin/embedding/switch", json={
                "model_name": target,
                "reindex": False,
            })
        # Query DB directly
        from src.core.database import SessionLocal
        from src.core.models import SystemConfig
        db = SessionLocal()
        cfg = db.get(SystemConfig, "embedding_model")
        db.close()
        assert cfg is not None
        assert cfg.value == target

    def test_switch_updates_active_model(self, as_admin):
        target = SUPPORTED_MODELS[1]["name"]
        with patch("src.core.embeddings.switch_model") as mock_switch:
            as_admin.post("/api/admin/embedding/switch", json={
                "model_name": target,
                "reindex": False,
            })
        mock_switch.assert_called_once_with(target)

    def test_concurrent_switch_returns_409(self, as_admin):
        import src.api.routes.admin as admin_module
        admin_module._reindex["running"] = True
        try:
            resp = as_admin.post("/api/admin/embedding/switch", json={
                "model_name": SUPPORTED_MODELS[0]["name"],
                "reindex": False,
            })
            assert resp.status_code == 409
        finally:
            admin_module._reindex["running"] = False

    def test_requires_admin(self, as_user):
        resp = as_user.post("/api/admin/embedding/switch", json={
            "model_name": SUPPORTED_MODELS[0]["name"],
            "reindex": False,
        })
        assert resp.status_code == 403


class TestReindexStatus:

    def test_status_returns_expected_fields(self, as_admin):
        resp = as_admin.get("/api/admin/embedding/status")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("running", "phase", "total", "done", "error"):
            assert field in data, f"missing field: {field}"

    def test_status_idle_by_default(self, as_admin):
        resp = as_admin.get("/api/admin/embedding/status")
        data = resp.json()
        assert data["running"] is False
        assert data["phase"] is None

    def test_status_after_switch_no_reindex_is_done(self, as_admin):
        with patch("src.core.embeddings.switch_model"):
            as_admin.post("/api/admin/embedding/switch", json={
                "model_name": SUPPORTED_MODELS[0]["name"],
                "reindex": False,
            })
        status = as_admin.get("/api/admin/embedding/status").json()
        assert status["running"] is False
        assert status["phase"] == "done"

    def test_requires_admin(self, as_user):
        assert as_user.get("/api/admin/embedding/status").status_code == 403
