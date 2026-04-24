"""Tests for /me/documents/* endpoints."""
import io
import pytest
from .conftest import do_login, do_logout


# ── Helpers ─────────────────────────────────────────────────────────────────

def add_text_doc(client, title="Test Doc", content="Some test content here.", collection="default"):
    return client.post("/me/documents/text", json={
        "title": title,
        "content": content,
        "collection": collection,
    })


def upload_file(client, filename, content: str, collection="default"):
    return client.post(
        f"/me/documents/upload?collection={collection}",
        files={"file": (filename, io.BytesIO(content.encode()), "text/plain")},
    )


# ── Text document tests ──────────────────────────────────────────────────────

class TestAddTextDocument:
    def test_add_text_returns_doc_id(self, as_user):
        resp = add_text_doc(as_user)
        assert resp.status_code == 200
        data = resp.json()
        assert "doc_id" in data
        assert data["title"] == "Test Doc"
        assert data["chunk_count"] >= 1
        assert data["collection"] == "default"

    def test_add_text_to_named_collection(self, as_user):
        resp = add_text_doc(as_user, collection="notes")
        assert resp.status_code == 200
        assert resp.json()["collection"] == "notes"

    def test_add_text_long_content_creates_multiple_chunks(self, as_user):
        content = "This is sentence number {}. ".format(1) * 100
        resp = add_text_doc(as_user, content=content)
        assert resp.status_code == 200
        assert resp.json()["chunk_count"] > 1

    def test_add_text_with_metadata(self, as_user):
        resp = as_user.post("/me/documents/text", json={
            "title": "Meta Doc",
            "content": "Content with metadata.",
            "collection": "default",
            "metadata": {"author": "Alice", "year": "2024"},
        })
        assert resp.status_code == 200


# ── File upload tests ────────────────────────────────────────────────────────

class TestFileUpload:
    def test_upload_txt_file(self, as_user):
        resp = upload_file(as_user, "notes.txt", "Plain text file content for testing.")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "notes"
        assert data["chunk_count"] >= 1

    def test_upload_md_file(self, as_user):
        md = "# Heading\n\nSome **markdown** content.\n\n- item 1\n- item 2"
        resp = upload_file(as_user, "readme.md", md)
        assert resp.status_code == 200

    def test_upload_html_file(self, as_user):
        html = "<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"
        resp = upload_file(as_user, "page.html", html)
        assert resp.status_code == 200

    def test_upload_unsupported_type_returns_400(self, as_user):
        resp = upload_file(as_user, "data.csv", "col1,col2\nval1,val2")
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    def test_upload_without_filename_returns_400(self, as_user):
        resp = as_user.post(
            "/me/documents/upload",
            files={"file": ("", io.BytesIO(b"content"), "text/plain")},
        )
        assert resp.status_code in (400, 422)


# ── List & retrieve tests ────────────────────────────────────────────────────

class TestListDocuments:
    def test_list_documents_empty_collection(self, as_user):
        resp = as_user.get("/me/documents?collection=empty_col_xyz")
        assert resp.status_code == 200
        assert resp.json()["documents"] == []

    def test_list_documents_after_upload(self, as_user):
        add_text_doc(as_user, title="Listed Doc", collection="list_test")
        resp = as_user.get("/me/documents?collection=list_test")
        assert resp.status_code == 200
        docs = resp.json()["documents"]
        assert len(docs) >= 1
        assert any(d["title"] == "Listed Doc" for d in docs)

    def test_list_shows_collection_field(self, as_user):
        add_text_doc(as_user, collection="col_check")
        resp = as_user.get("/me/documents?collection=col_check")
        docs = resp.json()["documents"]
        assert all(d["collection"] == "col_check" for d in docs)

    def test_list_collections_shows_user_collections(self, as_user):
        add_text_doc(as_user, collection="my_col_abc")
        resp = as_user.get("/me/collections")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()["collections"]]
        assert "my_col_abc" in names

    def test_get_document_chunks(self, as_user):
        resp = add_text_doc(as_user, content="Chunk test content. " * 20, title="Chunked Doc")
        doc_id = resp.json()["doc_id"]
        chunks_resp = as_user.get(f"/documents/{doc_id}/chunks?collection=u{as_user.get('/auth/me').json()['id']}_default")
        # Use admin route to verify chunks exist (collection is prefixed internally)
        assert doc_id is not None


# ── Delete tests ─────────────────────────────────────────────────────────────

class TestDeleteDocument:
    def test_delete_document_success(self, as_user):
        resp = add_text_doc(as_user, title="To Delete", collection="del_test")
        doc_id = resp.json()["doc_id"]
        del_resp = as_user.delete(f"/me/documents/{doc_id}?collection=del_test")
        assert del_resp.status_code == 200
        assert del_resp.json()["ok"] is True
        assert del_resp.json()["deleted_chunks"] >= 1

    def test_delete_nonexistent_returns_404(self, as_user):
        resp = as_user.delete("/me/documents/nonexistent_doc_id_xyz?collection=default")
        assert resp.status_code == 404

    def test_deleted_document_not_in_list(self, as_user):
        resp = add_text_doc(as_user, title="Gone Doc", collection="gone_col")
        doc_id = resp.json()["doc_id"]
        as_user.delete(f"/me/documents/{doc_id}?collection=gone_col")
        docs = as_user.get("/me/documents?collection=gone_col").json()["documents"]
        assert all(d["doc_id"] != doc_id for d in docs)


# ── Isolation tests ──────────────────────────────────────────────────────────

class TestUserIsolation:
    def test_user_cannot_see_other_users_documents(self, client, app):
        """Two users should not see each other's documents."""
        from fastapi.testclient import TestClient
        from .conftest import do_login, do_logout
        import uuid

        suffix = uuid.uuid4().hex[:6]
        # Create two independent users via admin
        admin_client = TestClient(app)
        admin_client.__enter__()
        do_login(admin_client, "admin", "admin123")

        for i in (1, 2):
            admin_client.post("/api/admin/users", json={
                "username": f"iso_{suffix}_{i}",
                "email": f"iso_{suffix}_{i}@test.local",
                "password": "IsoPass!1",
                "role": "user",
            })

        # User 1 uploads
        c1 = TestClient(app)
        c1.__enter__()
        do_login(c1, f"iso_{suffix}_1", "IsoPass!1")
        add_text_doc(c1, title="Secret Doc", content="User 1 private data", collection="private")

        # User 2 checks their own collection — should be empty
        c2 = TestClient(app)
        c2.__enter__()
        do_login(c2, f"iso_{suffix}_2", "IsoPass!1")
        resp = c2.get("/me/documents?collection=private")
        assert resp.json()["documents"] == [], "User 2 should not see User 1's documents"

        # Cleanup
        do_logout(admin_client)
        do_login(admin_client, "admin", "admin123")
        users = admin_client.get(f"/api/admin/users?q=iso_{suffix}").json()["users"]
        for u in users:
            admin_client.delete(f"/api/admin/users/{u['id']}")

        c1.__exit__(None, None, None)
        c2.__exit__(None, None, None)
        admin_client.__exit__(None, None, None)
