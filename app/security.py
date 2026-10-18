"""Password hashing and JWT helpers."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings


def hash_password(plain: str) -> str:
    # bcrypt operates on <=72 bytes; it truncates silently, which is standard.
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> str:
    settings = get_settings()
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode & verify a JWT. Raises jwt.PyJWTError on any problem."""
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def generate_refresh_token() -> str:
    """A high-entropy opaque refresh token (returned to the client once)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    """SHA-256 of the refresh token; only this hash is stored at rest."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
