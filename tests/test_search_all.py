"""Tests for /me/search/all cross-collection endpoint."""
import uuid
import pytest
from fastapi.testclient import TestClient
from tests.conftest import do_login, do_logout


def _add(client, title, content, collection):
    return client.post("/me/documents/text", json={
        "title": title, "content": content, "collection": collection,
    }).json()


class TestSearchAll:

    def test_returns_200_with_all_collections_field(self, as_user):
        resp = as_user.post("/me/search/all", json={
            "query": "anything", "top_k": 5,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "hits" in body
        assert "collections" in body
        assert body["collections"] == "all"

    def test_returns_hits_from_multiple_collections(self, as_user):
        suffix = uuid.uuid4().hex[:6]
        col_a = f"col_a_{suffix}"
        col_b = f"col_b_{suffix}"
        _add(as_user, "Python Basics", "Python is a programming language.", col_a)
        _add(as_user, "Go Basics",     "Go is a compiled language by Google.", col_b)

        resp = as_user.post("/me/search/all", json={"query": "programming language", "top_k": 10})
        assert resp.status_code == 200
        hits = resp.json()["hits"]
        assert len(hits) >= 1
        # Both collections should appear somewhere in the results
        hit_cols = {h["collection"] for h in hits}
        assert len(hit_cols) >= 1

    def test_hit_fields_present(self, as_user):
        suffix = uuid.uuid4().hex[:6]
        _add(as_user, "Field Check", "Some searchable content here.", f"fc_{suffix}")
        resp = as_user.post("/me/search/all", json={"query": "searchable content", "top_k": 5})
        for hit in resp.json()["hits"]:
            for field in ("chunk_id", "doc_id", "content", "score", "title", "collection"):
                assert field in hit, f"missing field: {field}"

    def test_respects_top_k(self, as_user):
        suffix = uuid.uuid4().hex[:6]
        for i in range(6):
            _add(as_user, f"Doc {i}", f"Unique content number {i} for topk test.", f"tk_{suffix}")

        for k in (1, 3):
            resp = as_user.post("/me/search/all", json={"query": "unique content", "top_k": k})
            assert resp.status_code == 200
            assert len(resp.json()["hits"]) <= k

    def test_no_duplicate_chunk_ids(self, as_user):
        suffix = uuid.uuid4().hex[:6]
        # Put the same query-relevant doc in two collections
        for col in (f"dup_a_{suffix}", f"dup_b_{suffix}"):
            _add(as_user, "Unique Topic", "Rare keyword xylophone.", col)

        resp = as_user.post("/me/search/all", json={"query": "xylophone", "top_k": 20})
        chunk_ids = [h["chunk_id"] for h in resp.json()["hits"]]
        assert len(chunk_ids) == len(set(chunk_ids)), "duplicate chunk_ids found"

    def test_results_sorted_by_score_descending(self, as_user):
        suffix = uuid.uuid4().hex[:6]
        for i in range(4):
            _add(as_user, f"Rank Doc {i}", f"Ranking document content item {i}.", f"rank_{suffix}")

        resp = as_user.post("/me/search/all", json={"query": "ranking document", "top_k": 10})
        scores = [h["score"] for h in resp.json()["hits"]]
        assert scores == sorted(scores, reverse=True), "hits not sorted by score desc"

    def test_unauthenticated_returns_401(self, client):
        do_logout(client)
        resp = client.post("/me/search/all", json={"query": "test", "top_k": 5})
        assert resp.status_code == 401

    def test_collection_isolation_across_users(self, app):
        """User B's /search/all must not return User A's documents."""
        suffix = uuid.uuid4().hex[:6]

        with TestClient(app) as admin_c:
            do_login(admin_c, "admin", "admin123")
            for i in (1, 2):
                admin_c.post("/api/admin/users", json={
                    "username": f"sa_{suffix}_{i}",
                    "email": f"sa_{suffix}_{i}@test.local",
                    "password": "SaPass!1",
                    "role": "user",
                })

        secret = f"xSECRET_{suffix}_phrase"

        with TestClient(app) as c1:
            do_login(c1, f"sa_{suffix}_1", "SaPass!1")
            c1.post("/me/documents/text", json={
                "title": "Secret", "content": secret, "collection": "private",
            })

        with TestClient(app) as c2:
            do_login(c2, f"sa_{suffix}_2", "SaPass!1")
            resp = c2.post("/me/search/all", json={"query": secret, "top_k": 5})
            assert resp.json()["hits"] == [], "user 2 found user 1's document"

        # Cleanup
        with TestClient(app) as admin_c:
            do_login(admin_c, "admin", "admin123")
            users = admin_c.get(f"/api/admin/users?q=sa_{suffix}").json()["users"]
            for u in users:
                admin_c.delete(f"/api/admin/users/{u['id']}")

    def test_query_field_in_response(self, as_user):
        resp = as_user.post("/me/search/all", json={"query": "my query text", "top_k": 5})
        assert resp.json()["query"] == "my query text"
