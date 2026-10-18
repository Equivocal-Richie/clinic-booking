"""Idempotency-Key handling for write endpoints.

Lets a client safely retry a POST (network blip, double-click, mobile resend)
without creating a duplicate appointment. The client sends a stable
`Idempotency-Key` header; the first request does the work and stores its
response, and any replay with the same key returns that stored response instead
of booking again.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..models import IdempotencyKey


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _get(session: Session, user_id: int, key: str) -> IdempotencyKey | None:
    return session.exec(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.idem_key == key
        )
    ).first()


def try_begin(
    session: Session, user_id: int, key: str, fp: str
) -> IdempotencyKey | None:
    """Claim the key. Returns None if we now own it, or the existing row if a
    request with this key already exists (completed or in-flight)."""
    row = IdempotencyKey(
        user_id=user_id, idem_key=key, request_fingerprint=fp, status="processing"
    )
    session.add(row)
    try:
        session.commit()
        return None
    except IntegrityError:
        session.rollback()
        return _get(session, user_id, key)


def complete(
    session: Session, user_id: int, key: str, status_code: int, body: dict
) -> None:
    row = _get(session, user_id, key)
    if row is not None:
        row.status = "completed"
        row.response_status = status_code
        row.response_body = json.dumps(body)
        session.add(row)
        session.commit()


def abort(session: Session, user_id: int, key: str) -> None:
    """Release the key after a failed attempt so the client may retry with it."""
    row = _get(session, user_id, key)
    if row is not None:
        session.delete(row)
        session.commit()
