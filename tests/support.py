"""Shared helpers for building deterministic future slot times in tests."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

CLINIC_TZ = ZoneInfo("Africa/Nairobi")


def next_weekday_local(weekday: int = 0, weeks_ahead: int = 1) -> date:
    """A date on the given weekday (Mon=0), at least `weeks_ahead` weeks out.

    Far enough in the future that the past/lead-time rules never interfere with
    happy-path tests that use the real clock.
    """
    base = datetime.now(CLINIC_TZ).date() + timedelta(weeks=weeks_ahead)
    delta = (weekday - base.weekday()) % 7
    return base + timedelta(days=delta)


def local_slot(hour: int, minute: int = 0, weekday: int = 0, weeks_ahead: int = 1) -> datetime:
    """A timezone-aware clinic-local datetime for a future slot."""
    d = next_weekday_local(weekday, weeks_ahead)
    return datetime.combine(d, time(hour, minute), tzinfo=CLINIC_TZ)


def utc_slot(hour: int, minute: int = 0, weekday: int = 0, weeks_ahead: int = 1) -> datetime:
    """Same as local_slot but expressed in UTC (for service-layer calls)."""
    return local_slot(hour, minute, weekday, weeks_ahead).astimezone(timezone.utc)
