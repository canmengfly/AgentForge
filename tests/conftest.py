"""
Test configuration.

IMPORTANT: env vars must be set BEFORE any `src.*` import, because pydantic-settings
and SQLAlchemy read them at module-import time.
"""
import os
import tempfile
import uuid
from pathlib import Path

# ── Override settings before src is ever imported ──────────────────────────
_TMPDIR = tempfile.mkdtemp(prefix="akp_test_")
Path(_TMPDIR, "chroma").mkdir(parents=True, exist_ok=True)

os.environ.update(
    {
        "DATA_DIR": _TMPDIR,
        "CHROMA_PERSIST_DIR": str(Path(_TMPDIR) / "chroma"),
        "JWT_SECRET": "test-jwt-secret-key-must-be-32ch",
        "API_KEY": "",
        "VECTOR_BACKEND": "chroma",
    }
)
# ───────────────────────────────────────────────────────────────────────────

import numpy as np
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch


# ── Deterministic fake embeddings (no model download) ──────────────────────

def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    results = []
    for text in texts:
        seed = abs(hash(text)) % (2**31)
        results.append(np.random.RandomState(seed).rand(384).tolist())
    return results


def _fake_embed_query(query: str) -> list[float]:
    seed = abs(hash(query)) % (2**31)
    return np.random.RandomState(seed).rand(384).tolist()


@pytest.fixture(scope="session", autouse=True)
def mock_embeddings():
    """Patch embedding calls so no model is downloaded during tests."""
    with (
        patch("src.core.chroma_vector_store.embed_texts", side_effect=_fake_embed_texts),
        patch("src.core.chroma_vector_store.embed_query", side_effect=_fake_embed_query),
        patch("src.core.embeddings.get_model", return_value=MagicMock()),
    ):
        yield


# ── App / client fixtures ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app(mock_embeddings):
    from src.api.main import app as _app
    return _app


@pytest.fixture(scope="session")
def client(app):
    """Single shared TestClient; tests manage login state explicitly."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Auth helpers ────────────────────────────────────────────────────────────

def do_login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    return resp


def do_logout(client: TestClient) -> None:
    client.post("/auth/logout")


# ── Reusable login fixtures (function-scoped → login/logout per test) ───────

@pytest.fixture
def as_admin(client):
    resp = do_login(client, "admin", "admin123")
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    yield client
    do_logout(client)


@pytest.fixture
def created_user(as_admin):
    """Create a fresh test user via admin API; delete after the test."""
    suffix = uuid.uuid4().hex[:6]
    data = {
        "username": f"u_{suffix}",
        "email": f"u_{suffix}@test.local",
        "password": "Passw0rd!",
        "role": "user",
    }
    resp = as_admin.post("/api/admin/users", json=data)
    assert resp.status_code == 201, resp.text
    user = resp.json()
    yield {**data, **user}
    do_logout(as_admin)
    do_login(as_admin, "admin", "admin123")
    as_admin.delete(f"/api/admin/users/{user['id']}")
    do_logout(as_admin)


@pytest.fixture
def as_user(client, created_user):
    """Log in as the freshly created test user."""
    resp = do_login(client, created_user["username"], created_user["password"])
    assert resp.status_code == 200, f"User login failed: {resp.text}"
    yield client
    do_logout(client)
