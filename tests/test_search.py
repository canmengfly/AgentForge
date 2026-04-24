"""Tests for /me/search endpoint."""
import pytest


def _add(client, title, content, collection="default"):
    return client.post("/me/documents/text", json={
        "title": title, "content": content, "collection": collection
    }).json()


class TestSearch:
    def test_search_empty_collection_returns_empty_list(self, as_user):
        resp = as_user.post("/me/search", json={
            "query": "anything",
            "collection": "empty_search_col",
            "top_k": 5,
        })
        assert resp.status_code == 200
        assert resp.json()["hits"] == []

    def test_search_returns_hits_after_upload(self, as_user):
        _add(as_user, "Python Guide", "Python is a programming language.", "search_test")
        _add(as_user, "Go Guide", "Go is a compiled language by Google.", "search_test")

        resp = as_user.post("/me/search", json={
            "query": "programming language",
            "collection": "search_test",
            "top_k": 5,
        })
        assert resp.status_code == 200
        hits = resp.json()["hits"]
        assert len(hits) >= 1

    def test_search_hit_fields(self, as_user):
        _add(as_user, "Fields Doc", "Content for field checking.", "fields_col")
        resp = as_user.post("/me/search", json={
            "query": "field checking",
            "collection": "fields_col",
        })
        hit = resp.json()["hits"][0]
        for field in ("chunk_id", "doc_id", "content", "score", "title"):
            assert field in hit, f"Missing field: {field}"

    def test_search_score_between_0_and_1(self, as_user):
        _add(as_user, "Score Doc", "Scoring test content.", "score_col")
        resp = as_user.post("/me/search", json={
            "query": "test scoring",
            "collection": "score_col",
        })
        for hit in resp.json()["hits"]:
            assert 0.0 <= hit["score"] <= 1.0, f"Score out of range: {hit['score']}"

    def test_search_respects_top_k(self, as_user):
        for i in range(10):
            _add(as_user, f"Doc {i}", f"Unique content for document number {i}.", "topk_col")

        for k in (1, 3, 5):
            resp = as_user.post("/me/search", json={
                "query": "document content",
                "collection": "topk_col",
                "top_k": k,
            })
            assert len(resp.json()["hits"]) <= k

    def test_search_response_contains_query_field(self, as_user):
        _add(as_user, "Query Doc", "Some content.", "qcol")
        resp = as_user.post("/me/search", json={
            "query": "my specific query",
            "collection": "qcol",
        })
        assert resp.json()["query"] == "my specific query"
        assert resp.json()["collection"] == "qcol"

    def test_search_unauthenticated_returns_401(self, client):
        from .conftest import do_logout
        do_logout(client)
        resp = client.post("/me/search", json={"query": "test", "collection": "default"})
        assert resp.status_code == 401

    def test_search_collection_isolation(self, client, app):
        """Searching in one user's namespace should not return another user's docs."""
        from fastapi.testclient import TestClient
        from .conftest import do_login, do_logout
        import uuid

        suffix = uuid.uuid4().hex[:6]
        admin_c = TestClient(app)
        admin_c.__enter__()
        do_login(admin_c, "admin", "admin123")
        for i in (1, 2):
            admin_c.post("/api/admin/users", json={
                "username": f"src_{suffix}_{i}",
                "email": f"src_{suffix}_{i}@test.local",
                "password": "SrcPass!1",
                "role": "user",
            })

        # User 1 uploads a very specific document
        c1 = TestClient(app)
        c1.__enter__()
        do_login(c1, f"src_{suffix}_1", "SrcPass!1")
        c1.post("/me/documents/text", json={
            "title": "Top Secret",
            "content": "xK9mN2pQ7rT exclusive content string",
            "collection": "secret",
        })

        # User 2 searches for the exact string — should get nothing
        c2 = TestClient(app)
        c2.__enter__()
        do_login(c2, f"src_{suffix}_2", "SrcPass!1")
        resp = c2.post("/me/search", json={
            "query": "xK9mN2pQ7rT exclusive content",
            "collection": "secret",
            "top_k": 5,
        })
        assert resp.json()["hits"] == [], "User 2 should not find User 1's documents"

        # Cleanup
        do_logout(admin_c)
        do_login(admin_c, "admin", "admin123")
        for u in admin_c.get(f"/api/admin/users?q=src_{suffix}").json()["users"]:
            admin_c.delete(f"/api/admin/users/{u['id']}")

        c1.__exit__(None, None, None)
        c2.__exit__(None, None, None)
        admin_c.__exit__(None, None, None)
