"""Unit tests for timezone normalisation."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.timeutils import to_utc

TZ = ZoneInfo("Africa/Nairobi")  # UTC+3, no DST


def test_naive_datetime_is_interpreted_as_clinic_local():
    naive = datetime(2026, 10, 20, 9, 0)  # 09:00 Nairobi
    result = to_utc(naive, TZ)
    assert result == datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)
    assert result.tzinfo == timezone.utc


def test_aware_datetime_is_converted_not_reinterpreted():
    aware = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    result = to_utc(aware, TZ)
    assert result == datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


def test_other_offset_is_respected():
    other = datetime(2026, 10, 20, 12, 0, tzinfo=ZoneInfo("Europe/London"))  # 11:00Z in Oct (BST)
    result = to_utc(other, TZ)
    assert result == datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc)
