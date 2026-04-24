from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func

from src.core.auth import hash_password
from src.core.deps import CurrentAdmin, DBSession
from src.core.models import User, UserRole
from src.core.vector_store import list_collections

router = APIRouter(prefix="/admin", tags=["admin"])


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
