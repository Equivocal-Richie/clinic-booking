"""Small indirection so the service layer reads runtime config in one place."""
from __future__ import annotations

from datetime import tzinfo

from ..config import get_settings


def get_runtime() -> tuple[tzinfo, int, int]:
    """Return (clinic timezone, slot duration minutes, min lead minutes)."""
    s = get_settings()
    return s.tz, s.slot_duration_minutes, s.min_lead_minutes
