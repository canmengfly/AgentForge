from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.auth import create_access_token, hash_password, verify_password
from src.core.database import get_db
from src.core.deps import CurrentUser
from src.core.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
async def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token(user.id, user.username, user.role.value)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return {"ok": True, "user": user.to_dict()}


@router.post("/token")
async def get_bearer_token(body: LoginRequest, db: Session = Depends(get_db)):
    """Return a Bearer token for programmatic / agent use."""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    token = create_access_token(user.id, user.username, user.role.value)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"ok": True}


@router.get("/me")
async def me(current_user: CurrentUser):
    return current_user.to_dict()


@router.put("/me/password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password incorrect")
    db_user = db.get(User, current_user.id)
    db_user.hashed_password = hash_password(body.new_password)
    db.commit()
    return {"ok": True}
