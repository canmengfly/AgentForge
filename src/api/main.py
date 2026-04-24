from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.core.config import settings
from src.api.routes import collections, config_export, documents, search
from src.api.routes import auth_routes, admin, me, pages


def _bootstrap_admin():
    """Create a default admin account on first run if no users exist."""
    from src.core.database import SessionLocal
    from src.core.models import User, UserRole
    from src.core.auth import hash_password

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin_user = User(
                username="admin",
                email="admin@localhost",
                hashed_password=hash_password("admin123"),
                role=UserRole.admin,
            )
            db.add(admin_user)
            db.commit()
            print("\n" + "=" * 50)
            print("  Default admin account created:")
            print("  Username : admin")
            print("  Password : admin123")
            print("  ⚠  Change this password after first login!")
            print("=" * 50 + "\n")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.core.database import Base, engine
    Base.metadata.create_all(bind=engine)
    _bootstrap_admin()
    from src.core.vector_store import init_vector_db
    init_vector_db()
    from src.core.embeddings import get_model
    get_model()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Vector-based knowledge platform with user management and MCP server.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(pages.router)                      # HTML pages  /login /dashboard /admin …
app.include_router(auth_routes.router)                # /auth/*
app.include_router(admin.router, prefix="/api")       # /api/admin/*  (avoid collision with /admin page)
app.include_router(me.router)                         # /me/*
app.include_router(documents.router)                  # /documents/*  (legacy / MCP)
app.include_router(search.router)                     # /search       (legacy / MCP)
app.include_router(collections.router)                # /collections  (legacy / MCP)
app.include_router(config_export.router)              # /export/*


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


def run():
    import uvicorn
    uvicorn.run("src.api.main:app", host=settings.api_host, port=settings.api_port, reload=True)


if __name__ == "__main__":
    run()
