"""Timezone helpers. All storage/comparison happens in UTC."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def to_utc(dt: datetime, clinic_tz: ZoneInfo) -> datetime:
    """Normalise an incoming datetime to timezone-aware UTC.

    Decision (documented in README): a naive datetime is interpreted as
    clinic-local wall-clock time, not UTC. This matches how a receptionist
    thinks ("book 2pm") while keeping storage unambiguous. An aware datetime is
    respected and simply converted.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=clinic_tz)
    return dt.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)
