from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from .config import settings

ALGORITHM = "HS256"


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def create_access_token(user_id: int, username: str, role: str, expires_minutes: int | None = None) -> str:
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes or settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])


def generate_secret() -> str:
    return secrets.token_hex(32)


def generate_api_token() -> tuple[str, str]:
    """Return (full_token, display_prefix). Token format: aft_<32 url-safe chars>."""
    raw = secrets.token_urlsafe(24)
    full = "aft_" + raw
    prefix = full[:12]
    return full, prefix


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
