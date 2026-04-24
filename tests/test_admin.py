"""Tests for /admin/* endpoints (user management & stats)."""
import pytest
from .conftest import do_login, do_logout


class TestAdminStats:
    def test_get_stats_returns_expected_fields(self, as_admin):
        resp = as_admin.get("/api/admin/stats")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("total_users", "active_users", "admin_users",
                    "total_collections", "total_document_chunks"):
            assert key in data, f"Missing field: {key}"

    def test_stats_total_users_at_least_one(self, as_admin):
        resp = as_admin.get("/api/admin/stats")
        assert resp.json()["total_users"] >= 1

    def test_regular_user_cannot_access_stats(self, as_user):
        resp = as_user.get("/api/admin/stats")
        assert resp.status_code == 403

    def test_unauthenticated_cannot_access_stats(self, client):
        do_logout(client)
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 401


class TestListUsers:
    def test_list_users_returns_paginated_response(self, as_admin):
        resp = as_admin.get("/api/admin/users")
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data
        assert "total" in data
        assert isinstance(data["users"], list)

    def test_list_users_includes_admin(self, as_admin):
        resp = as_admin.get("/api/admin/users")
        usernames = [u["username"] for u in resp.json()["users"]]
        assert "admin" in usernames

    def test_search_by_username(self, as_admin):
        resp = as_admin.get("/api/admin/users?q=admin")
        users = resp.json()["users"]
        assert all("admin" in u["username"].lower() or "admin" in u["email"].lower()
                   for u in users)

    def test_filter_by_role_admin(self, as_admin):
        resp = as_admin.get("/api/admin/users?role=admin")
        users = resp.json()["users"]
        assert all(u["role"] == "admin" for u in users)

    def test_filter_by_role_user(self, as_admin, created_user):
        resp = as_admin.get("/api/admin/users?role=user")
        users = resp.json()["users"]
        assert all(u["role"] == "user" for u in users)

    def test_pagination(self, as_admin):
        resp = as_admin.get("/api/admin/users?page=1&page_size=1")
        data = resp.json()
        assert len(data["users"]) <= 1
        assert data["page"] == 1
        assert data["page_size"] == 1


class TestCreateUser:
    def test_create_user_success(self, as_admin):
        resp = as_admin.post("/api/admin/users", json={
            "username": "new_create_test",
            "email": "create@test.local",
            "password": "securepass",
            "role": "user",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "new_create_test"
        assert data["role"] == "user"
        assert data["is_active"] is True
        assert "id" in data
        # cleanup
        as_admin.delete(f"/api/admin/users/{data['id']}")

    def test_create_admin_user(self, as_admin):
        resp = as_admin.post("/api/admin/users", json={
            "username": "new_admin_test",
            "email": "newadmin@test.local",
            "password": "securepass",
            "role": "admin",
        })
        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"
        as_admin.delete(f"/api/admin/users/{resp.json()['id']}")

    def test_duplicate_username_returns_400(self, as_admin):
        resp = as_admin.post("/api/admin/users", json={
            "username": "admin",
            "email": "another@test.local",
            "password": "pass",
        })
        assert resp.status_code == 400
        assert "Username" in resp.json()["detail"]

    def test_duplicate_email_returns_400(self, as_admin):
        resp = as_admin.post("/api/admin/users", json={
            "username": "unique_name_xyz",
            "email": "admin@localhost",  # admin's email
            "password": "pass",
        })
        assert resp.status_code == 400


class TestUpdateUser:
    def test_update_email(self, as_admin, created_user):
        uid = created_user["id"]
        resp = as_admin.put(f"/api/admin/users/{uid}", json={"email": "updated@test.local"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "updated@test.local"

    def test_promote_user_to_admin(self, as_admin, created_user):
        uid = created_user["id"]
        resp = as_admin.put(f"/api/admin/users/{uid}", json={"role": "admin"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"
        # demote back
        as_admin.put(f"/api/admin/users/{uid}", json={"role": "user"})

    def test_disable_user(self, as_admin, created_user):
        uid = created_user["id"]
        resp = as_admin.put(f"/api/admin/users/{uid}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_enable_user(self, as_admin, created_user):
        uid = created_user["id"]
        as_admin.put(f"/api/admin/users/{uid}", json={"is_active": False})
        resp = as_admin.put(f"/api/admin/users/{uid}", json={"is_active": True})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

    def test_reset_password_via_admin(self, as_admin, created_user, client):
        uid = created_user["id"]
        resp = as_admin.put(f"/api/admin/users/{uid}", json={"new_password": "BrandNewPass!"})
        assert resp.status_code == 200
        # Verify the new password works
        do_logout(client)
        login_resp = do_login(client, created_user["username"], "BrandNewPass!")
        assert login_resp.status_code == 200
        do_logout(client)

    def test_update_nonexistent_user_returns_404(self, as_admin):
        resp = as_admin.put("/api/admin/users/999999", json={"email": "x@x.com"})
        assert resp.status_code == 404

    def test_admin_cannot_demote_self(self, as_admin):
        me = as_admin.get("/auth/me").json()
        resp = as_admin.put(f"/api/admin/users/{me['id']}", json={"role": "user"})
        assert resp.status_code == 400


class TestDeleteUser:
    def test_delete_user_success(self, as_admin):
        resp = as_admin.post("/api/admin/users", json={
            "username": "to_delete",
            "email": "todelete@test.local",
            "password": "pass",
        })
        uid = resp.json()["id"]
        del_resp = as_admin.delete(f"/api/admin/users/{uid}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted_id"] == uid

        # Confirm gone
        users_resp = as_admin.get(f"/api/admin/users?q=to_delete")
        assert all(u["id"] != uid for u in users_resp.json()["users"])

    def test_delete_self_forbidden(self, as_admin):
        me = as_admin.get("/auth/me").json()
        resp = as_admin.delete(f"/api/admin/users/{me['id']}")
        assert resp.status_code == 400

    def test_delete_nonexistent_returns_404(self, as_admin):
        resp = as_admin.delete("/api/admin/users/999999")
        assert resp.status_code == 404


class TestAdminCollections:
    def test_list_all_collections(self, as_admin):
        resp = as_admin.get("/api/admin/collections")
        assert resp.status_code == 200
        assert "collections" in resp.json()
        assert isinstance(resp.json()["collections"], list)
