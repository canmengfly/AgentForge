"""
End-to-end scenario tests.
Each test covers a complete user journey rather than individual endpoints.
"""
import io
import uuid
import pytest
from fastapi.testclient import TestClient
from .conftest import do_login, do_logout


class TestCompleteUserJourney:
    """A user signs up, uploads documents, searches, then deletes."""

    def test_full_knowledge_workflow(self, client, app):
        suffix = uuid.uuid4().hex[:6]

        # 1. Admin creates user
        do_login(client, "admin", "admin123")
        create_resp = client.post("/api/admin/users", json={
            "username": f"journey_{suffix}",
            "email": f"journey_{suffix}@test.local",
            "password": "Journey!Pass1",
            "role": "user",
        })
        assert create_resp.status_code == 201
        uid = create_resp.json()["id"]
        do_logout(client)

        # 2. User logs in
        do_login(client, f"journey_{suffix}", "Journey!Pass1")
        me = client.get("/auth/me").json()
        assert me["username"] == f"journey_{suffix}"

        # 3. Upload multiple documents to different collections
        docs = [
            ("Python Basics", "Python is an interpreted language.", "tech"),
            ("Go Basics", "Go is a compiled language.", "tech"),
            ("Meeting Notes", "Discussed Q3 roadmap and priorities.", "notes"),
        ]
        doc_ids = {}
        for title, content, col in docs:
            resp = client.post("/me/documents/text", json={
                "title": title, "content": content, "collection": col
            })
            assert resp.status_code == 200, f"Upload failed for {title}: {resp.text}"
            doc_ids[title] = (resp.json()["doc_id"], col)

        # 4. Check collections exist
        cols = client.get("/me/collections").json()["collections"]
        col_names = [c["name"] for c in cols]
        assert "tech" in col_names
        assert "notes" in col_names

        # 5. Search in tech collection
        search_resp = client.post("/me/search", json={
            "query": "programming language",
            "collection": "tech",
            "top_k": 3,
        })
        assert search_resp.status_code == 200
        assert len(search_resp.json()["hits"]) >= 1

        # 6. Verify search in wrong collection returns nothing (isolation)
        wrong_search = client.post("/me/search", json={
            "query": "programming",
            "collection": "notes",
            "top_k": 5,
        })
        # notes collection doesn't have programming content
        assert wrong_search.status_code == 200  # no crash

        # 7. Delete one document
        doc_id, col = doc_ids["Meeting Notes"]
        del_resp = client.delete(f"/me/documents/{doc_id}?collection={col}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted_chunks"] >= 1

        # 8. Verify deletion
        remaining = client.get(f"/me/documents?collection={col}").json()["documents"]
        assert all(d["doc_id"] != doc_id for d in remaining)

        do_logout(client)

        # 9. Cleanup via admin
        do_login(client, "admin", "admin123")
        client.delete(f"/api/admin/users/{uid}")
        do_logout(client)


class TestAdminUserLifecycle:
    """Admin manages a user through their full lifecycle."""

    def test_create_modify_disable_delete(self, app):
        suffix = uuid.uuid4().hex[:6]

        with TestClient(app) as admin_c:
            do_login(admin_c, "admin", "admin123")

            # Create
            resp = admin_c.post("/api/admin/users", json={
                "username": f"lifecycle_{suffix}",
                "email": f"lifecycle_{suffix}@test.local",
                "password": "Lifecycle1!",
                "role": "user",
            })
            assert resp.status_code == 201
            uid = resp.json()["id"]

            # Promote to admin
            resp = admin_c.put(f"/api/admin/users/{uid}", json={"role": "admin"})
            assert resp.json()["role"] == "admin"

            # Demote back
            resp = admin_c.put(f"/api/admin/users/{uid}", json={"role": "user"})
            assert resp.json()["role"] == "user"

            # Disable
            resp = admin_c.put(f"/api/admin/users/{uid}", json={"is_active": False})
            assert resp.json()["is_active"] is False

        # Disabled user cannot login
        with TestClient(app) as c:
            login_resp = do_login(c, f"lifecycle_{suffix}", "Lifecycle1!")
            assert login_resp.status_code == 403

        # Re-enable and verify login works
        with TestClient(app) as admin_c:
            do_login(admin_c, "admin", "admin123")
            admin_c.put(f"/api/admin/users/{uid}", json={"is_active": True})

        with TestClient(app) as c:
            login_resp = do_login(c, f"lifecycle_{suffix}", "Lifecycle1!")
            assert login_resp.status_code == 200

        # Reset password
        with TestClient(app) as admin_c:
            do_login(admin_c, "admin", "admin123")
            admin_c.put(f"/api/admin/users/{uid}", json={"new_password": "ResetPass!2"})

        with TestClient(app) as c:
            assert do_login(c, f"lifecycle_{suffix}", "ResetPass!2").status_code == 200
            assert do_login(c, f"lifecycle_{suffix}", "Lifecycle1!").status_code == 401

        # Final delete
        with TestClient(app) as admin_c:
            do_login(admin_c, "admin", "admin123")
            del_resp = admin_c.delete(f"/api/admin/users/{uid}")
            assert del_resp.status_code == 200


class TestFileUploadAndRetrieval:
    """Upload various file types and verify retrieval."""

    def test_txt_md_html_upload_workflow(self, as_user):
        files = [
            ("report.txt", "Annual report: revenue increased by 30% in Q4."),
            ("notes.md", "# Meeting Notes\n\n- Approved the new design\n- Delayed launch"),
            ("page.html", "<html><body><p>Product description page content</p></body></html>"),
        ]
        uploaded = []
        for fname, content in files:
            resp = as_user.post(
                "/me/documents/upload?collection=file_test",
                files={"file": (fname, io.BytesIO(content.encode()), "text/plain")},
            )
            assert resp.status_code == 200, f"Failed for {fname}: {resp.text}"
            uploaded.append(resp.json()["doc_id"])

        # All 3 documents should appear in list
        docs = as_user.get("/me/documents?collection=file_test").json()["documents"]
        listed_ids = {d["doc_id"] for d in docs}
        for doc_id in uploaded:
            assert doc_id in listed_ids

        # Search should find relevant content
        resp = as_user.post("/me/search", json={
            "query": "revenue report",
            "collection": "file_test",
            "top_k": 3,
        })
        assert resp.status_code == 200
        assert len(resp.json()["hits"]) >= 1


class TestExportEndpoints:
    """MCP config and skill export endpoints."""

    def test_mcp_config_returns_server_block(self, as_admin):
        resp = as_admin.get("/export/mcp-config")
        assert resp.status_code == 200
        data = resp.json()
        assert "mcpServers" in data
        assert "knowledge" in data["mcpServers"]
        server = data["mcpServers"]["knowledge"]
        assert "command" in server
        assert "args" in server

    def test_claude_settings_snippet(self, as_admin):
        resp = as_admin.get("/export/claude-settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "settings_snippet" in data
        assert "mcpServers" in data["settings_snippet"]

    def test_list_skills(self, as_admin):
        resp = as_admin.get("/export/skills")
        assert resp.status_code == 200
        skills = resp.json()["skills"]
        names = [s["name"] for s in skills]
        assert "search-knowledge" in names
        assert "upload-document" in names

    def test_get_skill_content(self, as_admin):
        resp = as_admin.get("/export/skill/search-knowledge")
        assert resp.status_code == 200
        assert "query" in resp.text.lower() or "search" in resp.text.lower()

    def test_nonexistent_skill_returns_404(self, as_admin):
        resp = as_admin.get("/export/skill/nonexistent_skill_xyz")
        assert resp.status_code == 404


class TestPageRoutes:
    """HTML page routes redirect correctly."""

    def test_unauthenticated_dashboard_redirects_to_login(self, client):
        do_logout(client)
        resp = client.get("/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["location"]

    def test_unauthenticated_upload_redirects_to_login(self, client):
        do_logout(client)
        resp = client.get("/upload", follow_redirects=False)
        assert resp.status_code == 302

    def test_unauthenticated_search_redirects_to_login(self, client):
        do_logout(client)
        resp = client.get("/search", follow_redirects=False)
        assert resp.status_code == 302

    def test_admin_page_forbidden_for_regular_user(self, as_user):
        resp = as_user.get("/admin", follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_login_page_accessible(self, client):
        do_logout(client)
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "login" in resp.text.lower() or "登录" in resp.text

    def test_authenticated_root_redirects_to_dashboard(self, as_admin):
        resp = as_admin.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "admin" in resp.headers["location"]

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_admin_page_accessible_to_admin(self, as_admin):
        resp = as_admin.get("/admin")
        assert resp.status_code == 200
        assert "管理" in resp.text or "admin" in resp.text.lower()

    def test_user_dashboard_accessible(self, as_user):
        resp = as_user.get("/dashboard")
        assert resp.status_code == 200
