from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from .auth import decode_token
from .database import get_db
from .models import User, UserRole


def _get_user_from_api_token(token: str, db: Session) -> User:
    from datetime import datetime
    from .models import APIToken
    from .auth import hash_api_token

    token_hash = hash_api_token(token)
    api_token = db.query(APIToken).filter(APIToken.token_hash == token_hash).first()
    if not api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    user = db.get(User, api_token.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    api_token.last_used_at = datetime.utcnow()
    db.commit()
    return user


def _get_user_from_token(token: str, db: Session) -> User:
    if token.startswith("aft_"):
        return _get_user_from_api_token(token, db)
    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def _resolve_token(
    access_token: str | None,
    authorization: str | None,
) -> str | None:
    """Prefer cookie; fall back to Bearer token in Authorization header."""
    if access_token:
        return access_token
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def get_current_user(
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User:
    token = _resolve_token(access_token, authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _get_user_from_token(token, db)


def get_optional_user(
    access_token: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> User | None:
    token = _resolve_token(access_token, authorization)
    if not token:
        return None
    try:
        return _get_user_from_token(token, db)
    except HTTPException:
        return None


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
DBSession = Annotated[Session, Depends(get_db)]
