"""HTML page routes — render Jinja2 templates.

Uses Starlette 1.x TemplateResponse(request, name, context) signature.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.core.deps import get_optional_user
from src.core.models import User, UserRole

router = APIRouter(tags=["pages"])
# Resolve templates directory relative to this file so it works when installed via pip.
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _ctx(user: User | None, **extra) -> dict:
    """Build template context (request is passed separately in new Starlette API)."""
    return {"current_user": user, "UserRole": UserRole, **extra}


def _redirect_login():
    return RedirectResponse("/login", status_code=302)


def _redirect_dashboard(user: User):
    return RedirectResponse("/admin" if user.role == UserRole.admin else "/dashboard", status_code=302)


@router.get("/", response_class=HTMLResponse)
async def index(user: User | None = Depends(get_optional_user)):
    if user:
        return _redirect_dashboard(user)
    return RedirectResponse("/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user: User | None = Depends(get_optional_user)):
    if user:
        return _redirect_dashboard(user)
    return templates.TemplateResponse(request, "login.html", _ctx(None))


@router.get("/logout")
async def logout_page():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp


# ── User pages ──────────────────────────────────────────────────────────────


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return _redirect_login()
    return templates.TemplateResponse(request, "dashboard.html", _ctx(user))


@router.get("/upload")
async def upload_redirect():
    return RedirectResponse("/datasources", status_code=301)


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return _redirect_login()
    return templates.TemplateResponse(request, "search_page.html", _ctx(user))


@router.get("/chunks", response_class=HTMLResponse)
async def chunks_page(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return _redirect_login()
    return templates.TemplateResponse(request, "chunks.html", _ctx(user))


@router.get("/export", response_class=HTMLResponse)
async def export_page(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return _redirect_login()
    return templates.TemplateResponse(request, "export.html", _ctx(user))


@router.get("/datasources", response_class=HTMLResponse)
async def datasources_page(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return _redirect_login()
    return templates.TemplateResponse(request, "datasources.html", _ctx(user))


# ── Admin pages ──────────────────────────────────────────────────────────────


@router.get("/admin", response_class=HTMLResponse)
async def admin_index(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return _redirect_login()
    if user.role != UserRole.admin:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "admin/index.html", _ctx(user))


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return _redirect_login()
    if user.role != UserRole.admin:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "admin/users.html", _ctx(user))


@router.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request, user: User | None = Depends(get_optional_user)):
    if not user:
        return _redirect_login()
    if user.role != UserRole.admin:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "admin/settings.html", _ctx(user))
