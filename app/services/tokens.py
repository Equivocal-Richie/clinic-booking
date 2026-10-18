"""Refresh-token lifecycle: issue, rotate (on refresh), and revoke (on logout)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ..config import get_settings
from ..models import RefreshToken, User
from ..security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)


class RefreshError(Exception):
    """Raised when a refresh token is invalid, expired, or revoked."""


def _expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        days=get_settings().refresh_token_expire_days
    )


def _lookup(session: Session, raw: str) -> RefreshToken | None:
    return session.exec(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(raw)
        )
    ).first()


def revoke_all_for_user(session: Session, user_id: int) -> None:
    rows = session.exec(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked == False  # noqa: E712
        )
    ).all()
    for r in rows:
        r.revoked = True
        session.add(r)
    session.commit()


def issue_tokens(session: Session, user: User) -> tuple[str, str]:
    """Return (access_token_jwt, refresh_token_raw). Only the hash is stored."""
    access = create_access_token(user.id, user.role.value)
    raw = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id, token_hash=hash_refresh_token(raw), expires_at=_expiry()
        )
    )
    session.commit()
    return access, raw


def rotate(session: Session, raw: str) -> tuple[str, str, User]:
    """Validate a refresh token and rotate it: returns (access, new_refresh, user).

    Rotation revokes the presented token and issues a fresh one. Presenting an
    already-revoked token means reuse (likely theft) → all the user's tokens are
    revoked defensively.
    """
    rt = _lookup(session, raw)
    if rt is None:
        raise RefreshError("Invalid refresh token")

    if rt.revoked:
        revoke_all_for_user(session, rt.user_id)
        raise RefreshError("Refresh token has been revoked")

    expires_at = rt.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise RefreshError("Refresh token has expired")

    user = session.get(User, rt.user_id)
    if user is None or not user.is_active:
        raise RefreshError("Invalid refresh token")

    rt.revoked = True
    session.add(rt)
    access = create_access_token(user.id, user.role.value)
    new_raw = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(new_raw),
            expires_at=_expiry(),
        )
    )
    session.commit()
    return access, new_raw, user


def revoke(session: Session, raw: str) -> bool:
    rt = _lookup(session, raw)
    if rt is None or rt.revoked:
        return False
    rt.revoked = True
    session.add(rt)
    session.commit()
    return True
