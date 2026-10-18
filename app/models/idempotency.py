from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class IdempotencyKey(SQLModel, table=True):
    """Stores the outcome of a write keyed by a client-supplied Idempotency-Key.

    Scoped per user so one client's key can never replay another's response. The
    unique constraint on (user_id, idem_key) is the race arbiter: the first
    request to insert "owns" the key; a concurrent duplicate hits the constraint
    and reads back the in-flight/stored result instead of creating a second
    appointment.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "idem_key", name="uq_idem_user_key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    idem_key: str = Field(index=True)
    # Hash of the request body; lets us reject a key reused with a different payload.
    request_fingerprint: str
    status: str = Field(default="processing")  # 'processing' | 'completed'
    response_status: int | None = Field(default=None)
    response_body: str | None = Field(default=None)  # JSON text
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
