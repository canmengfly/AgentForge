"""Tests for /auth/* endpoints."""
import pytest
from .conftest import do_login, do_logout


class TestLogin:
    def test_admin_login_success(self, client):
        resp = do_login(client, "admin", "admin123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["username"] == "admin"
        assert data["user"]["role"] == "admin"
        assert data["ok"] is True
        do_logout(client)

    def test_wrong_password_returns_401(self, client):
        resp = do_login(client, "admin", "wrongpassword")
        assert resp.status_code == 401

    def test_nonexistent_user_returns_401(self, client):
        resp = do_login(client, "ghost_user_xyz", "anypassword")
        assert resp.status_code == 401

    def test_login_sets_cookie(self, client):
        resp = do_login(client, "admin", "admin123")
        assert resp.status_code == 200
        # TestClient stores cookies; verify the session is active
        me = client.get("/auth/me")
        assert me.status_code == 200
        do_logout(client)

    def test_disabled_user_cannot_login(self, as_admin):
        # Create user, disable, try login
        resp = as_admin.post("/api/admin/users", json={
            "username": "disabled_user",
            "email": "disabled@test.local",
            "password": "pass123",
            "role": "user",
        })
        uid = resp.json()["id"]

        as_admin.put(f"/api/admin/users/{uid}", json={"is_active": False})

        login_resp = do_login(as_admin, "disabled_user", "pass123")
        assert login_resp.status_code == 403

        as_admin.delete(f"/api/admin/users/{uid}")


class TestMe:
    def test_me_returns_current_user(self, as_admin):
        resp = as_admin.get("/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"

    def test_me_unauthenticated_returns_401(self, client):
        do_logout(client)
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_as_regular_user(self, as_user, created_user):
        resp = as_user.get("/auth/me")
        assert resp.status_code == 200
        assert resp.json()["username"] == created_user["username"]
        assert resp.json()["role"] == "user"


class TestLogout:
    def test_logout_ends_session(self, client):
        do_login(client, "admin", "admin123")
        assert client.get("/auth/me").status_code == 200
        do_logout(client)
        assert client.get("/auth/me").status_code == 401


class TestChangePassword:
    def test_change_password_success(self, as_user, created_user):
        resp = as_user.put("/auth/me/password", json={
            "current_password": created_user["password"],
            "new_password": "NewPassw0rd!",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Verify login with new password works
        do_logout(as_user)
        new_login = do_login(as_user, created_user["username"], "NewPassw0rd!")
        assert new_login.status_code == 200

    def test_change_password_wrong_current(self, as_user):
        resp = as_user.put("/auth/me/password", json={
            "current_password": "completely_wrong",
            "new_password": "NewPass123!",
        })
        assert resp.status_code == 400
