from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class RefreshToken(SQLModel, table=True):
    """A DB-backed refresh token (opaque, stored only as a SHA-256 hash).

    Storing a hash means a database leak never exposes a usable token. Keeping
    the row lets us revoke tokens (logout) and rotate them on every refresh — a
    presented-but-revoked token signals reuse of a stolen token.
    """

    __tablename__ = "refresh_tokens"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    revoked: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
