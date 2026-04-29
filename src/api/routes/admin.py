from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import func

from src.core.auth import hash_password
from src.core.config import SUPPORTED_MODELS, SUPPORTED_RERANKERS
from src.core.deps import CurrentAdmin, DBSession
from src.core.models import SystemConfig, User, UserRole
from src.core.vector_store import list_collections

router = APIRouter(prefix="/admin", tags=["admin"])

# ── In-memory reindex state (single-worker; reset on restart) ────────────────
_reindex: dict = {"running": False, "phase": None, "total": 0, "done": 0, "error": None}

# ── In-memory reranker loading state ─────────────────────────────────────────
_reranker_state: dict = {"loading": False, "error": None}


class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: UserRole = UserRole.user


class UpdateUserRequest(BaseModel):
    email: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    new_password: str | None = None


@router.get("/stats")
async def get_stats(_: CurrentAdmin, db: DBSession):
    total_users = db.query(func.count(User.id)).scalar()
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar()
    admin_users = db.query(func.count(User.id)).filter(User.role == UserRole.admin).scalar()
    collections = list_collections()
    total_docs = sum(c["count"] for c in collections)
    return {
        "total_users": total_users,
        "active_users": active_users,
        "admin_users": admin_users,
        "total_collections": len(collections),
        "total_document_chunks": total_docs,
    }


@router.get("/users")
async def list_users(
    _: CurrentAdmin,
    db: DBSession,
    q: str = "",
    role: str = "",
    page: int = 1,
    page_size: int = 20,
):
    query = db.query(User)
    if q:
        query = query.filter(
            User.username.ilike(f"%{q}%") | User.email.ilike(f"%{q}%")
        )
    if role and role in ("admin", "user"):
        query = query.filter(User.role == role)
    total = query.count()
    users = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "users": [u.to_dict() for u in users],
    }


@router.post("/users", status_code=201)
async def create_user(body: CreateUserRequest, _: CurrentAdmin, db: DBSession):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, f"Username '{body.username}' already exists")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, f"Email '{body.email}' already registered")
    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: UpdateUserRequest, admin: CurrentAdmin, db: DBSession):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and body.role == UserRole.user:
        raise HTTPException(400, "Cannot demote yourself")
    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.new_password:
        user.hashed_password = hash_password(body.new_password)
    db.commit()
    db.refresh(user)
    return user.to_dict()


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: CurrentAdmin, db: DBSession):
    if user_id == admin.id:
        raise HTTPException(400, "Cannot delete your own account")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
    return {"ok": True, "deleted_id": user_id}


@router.get("/collections")
async def all_collections(_: CurrentAdmin):
    return {"collections": list_collections()}


# ── Embedding model management ───────────────────────────────────────────────

@router.get("/embedding")
async def get_embedding_info(_: CurrentAdmin):
    from src.core.embeddings import get_active_model_name
    active = get_active_model_name()
    model_info = next(
        (m for m in SUPPORTED_MODELS if m["name"] == active),
        {"name": active, "dim": None, "lang": "—", "size_mb": None, "desc": "自定义模型"},
    )
    total_chunks = sum(c["count"] for c in list_collections())
    return {
        "current": model_info,
        "models": SUPPORTED_MODELS,
        "total_chunks": total_chunks,
        "reindex": dict(_reindex),
    }


class SwitchModelRequest(BaseModel):
    model_name: str
    reindex: bool = True


@router.post("/embedding/switch")
async def switch_embedding_model(
    body: SwitchModelRequest,
    bg: BackgroundTasks,
    _: CurrentAdmin,
    db: DBSession,
):
    model_info = next((m for m in SUPPORTED_MODELS if m["name"] == body.model_name), None)
    if not model_info:
        raise HTTPException(400, f"不支持的模型: {body.model_name}")
    if _reindex["running"]:
        raise HTTPException(409, "已有重建任务正在运行")

    # Persist selection to DB
    for key, val in [
        ("embedding_model", body.model_name),
        ("embedding_dim", str(model_info["dim"])),
    ]:
        cfg = db.get(SystemConfig, key)
        if cfg:
            cfg.value = val
            cfg.updated_at = datetime.utcnow()
        else:
            db.add(SystemConfig(key=key, value=val))
    db.commit()

    bg.add_task(_run_switch, body.model_name, body.reindex)
    return {"ok": True, "model": model_info, "reindexing": body.reindex}


@router.get("/embedding/status")
async def reindex_status(_: CurrentAdmin):
    return dict(_reindex)


# ── Background tasks ─────────────────────────────────────────────────────────

async def _run_switch(model_name: str, do_reindex: bool) -> None:
    global _reindex
    _reindex.update(running=True, phase="downloading", total=0, done=0, error=None)

    try:
        # Download / load model in a thread (blocking network/disk I/O)
        from src.core.embeddings import switch_model
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(pool, switch_model, model_name)

        if not do_reindex:
            _reindex["phase"] = "done"
            return

        _reindex["phase"] = "reindexing"
        await _reindex_all_collections()
        _reindex["phase"] = "done"

    except Exception as exc:
        _reindex["error"] = str(exc)
    finally:
        _reindex["running"] = False


async def _reindex_all_collections() -> None:
    """Re-embed every chunk with the currently active model (ChromaDB only)."""
    from src.core.config import settings
    from src.core.embeddings import embed_texts

    if settings.vector_backend != "chroma":
        return  # pgvector dim-change requires manual DDL migration

    from src.core.chroma_vector_store import _client
    client = _client()
    cols = list_collections()
    _reindex["total"] = sum(c["count"] for c in cols)

    EMBED_BATCH = 32  # safe for most RAM budgets

    for col_info in cols:
        name = col_info["name"]
        col = client.get_collection(name)

        # Collect all chunks (paginated to avoid OOM on huge collections)
        all_ids, all_docs, all_metas = [], [], []
        page_size, offset = 500, 0
        while True:
            page = col.get(include=["documents", "metadatas"], limit=page_size, offset=offset)
            if not page["ids"]:
                break
            all_ids.extend(page["ids"])
            all_docs.extend(page["documents"])
            all_metas.extend(page["metadatas"])
            offset += len(page["ids"])

        if not all_ids:
            continue

        # Rebuild the collection (dimension may have changed)
        client.delete_collection(name)
        new_col = client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})

        # Re-embed in batches, yield control between batches
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            for i in range(0, len(all_ids), EMBED_BATCH):
                batch_docs = all_docs[i: i + EMBED_BATCH]
                new_embeddings = await loop.run_in_executor(pool, embed_texts, batch_docs)
                new_col.add(
                    ids=all_ids[i: i + EMBED_BATCH],
                    embeddings=new_embeddings,
                    documents=batch_docs,
                    metadatas=all_metas[i: i + EMBED_BATCH],
                )
                _reindex["done"] += len(batch_docs)
                await asyncio.sleep(0)  # yield to event loop


# ── Reranker management ───────────────────────────────────────────────────────

class SwitchRerankerRequest(BaseModel):
    model_name: str  # empty string = disable reranker


@router.get("/reranker")
async def get_reranker_info(_: CurrentAdmin):
    from src.core.reranker import get_info
    return {**get_info(), "models": SUPPORTED_RERANKERS, **_reranker_state}


@router.post("/reranker/switch")
async def switch_reranker_endpoint(
    body: SwitchRerankerRequest,
    bg: BackgroundTasks,
    _: CurrentAdmin,
    db: DBSession,
):
    """Enable or switch the cross-encoder reranker (empty model_name = disable)."""
    if body.model_name and not any(m["name"] == body.model_name for m in SUPPORTED_RERANKERS):
        raise HTTPException(400, f"不支持的重排序模型: {body.model_name}")
    if _reranker_state["loading"]:
        raise HTTPException(409, "重排序模型正在加载中，请稍后")

    cfg = db.get(SystemConfig, "reranker_model")
    if cfg:
        cfg.value = body.model_name
        cfg.updated_at = datetime.utcnow()
    else:
        db.add(SystemConfig(key="reranker_model", value=body.model_name))
    db.commit()

    bg.add_task(_load_reranker_bg, body.model_name)
    return {"ok": True, "loading": bool(body.model_name), "model": body.model_name or None}


@router.get("/reranker/status")
async def get_reranker_status(_: CurrentAdmin):
    from src.core.reranker import get_info
    return {**get_info(), **_reranker_state}


async def _load_reranker_bg(model_name: str) -> None:
    global _reranker_state
    _reranker_state.update(loading=True, error=None)
    try:
        from src.core.reranker import switch_reranker
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(pool, switch_reranker, model_name)
    except Exception as exc:
        _reranker_state["error"] = str(exc)
    finally:
        _reranker_state["loading"] = False
