"""Unit tests for the pure slot-grid logic (no DB)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services import slots

TZ = ZoneInfo("Africa/Nairobi")
MON = date(2026, 10, 19)  # a Monday


def _local(h, m=0):
    return datetime.combine(MON, time(h, m), tzinfo=TZ).astimezone(timezone.utc)


def test_grid_with_lunch_break_has_expected_count_and_bounds():
    blocks = [(time(9, 0), time(13, 0)), (time(14, 0), time(17, 0))]
    grid = slots.generate_grid(blocks, MON, TZ, 30)
    # 4h + 3h = 7h -> 14 half-hour slots.
    assert len(grid) == 14
    assert grid[0] == _local(9, 0)
    assert grid[-1] == _local(16, 30)
    # Lunch gap excluded, end-of-day excluded.
    assert _local(13, 0) not in grid
    assert _local(13, 30) not in grid
    assert _local(17, 0) not in grid
    # First afternoon slot present.
    assert _local(14, 0) in grid


def test_last_slot_requires_full_duration_to_fit():
    # A 09:00-10:00 block yields 09:00 and 09:30 only (not 10:00).
    grid = slots.generate_grid([(time(9, 0), time(10, 0))], MON, TZ, 30)
    assert grid == [_local(9, 0), _local(9, 30)]


def test_block_too_short_for_a_slot_yields_nothing():
    grid = slots.generate_grid([(time(9, 0), time(9, 20))], MON, TZ, 30)
    assert grid == []


def test_empty_blocks_yields_empty_grid():
    assert slots.generate_grid([], MON, TZ, 30) == []


def test_overlapping_blocks_are_deduplicated():
    blocks = [(time(9, 0), time(11, 0)), (time(10, 0), time(12, 0))]
    grid = slots.generate_grid(blocks, MON, TZ, 30)
    assert len(grid) == len(set(grid))
    assert grid == sorted(grid)
    # 09:00..11:30 inclusive = 6 slots
    assert grid[0] == _local(9, 0)
    assert grid[-1] == _local(11, 30)
    assert len(grid) == 6


def test_available_slots_subtracts_booked_and_lead_cutoff():
    grid = [_local(9, 0), _local(9, 30), _local(10, 0)]
    now = _local(8, 0)  # same morning, 1h before first slot
    booked = {_local(9, 30)}
    # lead 60 min -> cutoff 09:00, so 09:00 is allowed (>= cutoff), 09:30 booked.
    avail = slots.available_slots(grid, booked, now, min_lead_minutes=60)
    assert avail == [_local(9, 0), _local(10, 0)]


def test_available_slots_respects_lead_time():
    grid = [_local(9, 0), _local(9, 30), _local(10, 0)]
    now = _local(9, 0)  # lead 60 -> cutoff 10:00
    avail = slots.available_slots(grid, set(), now, min_lead_minutes=60)
    assert avail == [_local(10, 0)]


def test_earliest_bookable():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert slots.earliest_bookable(now, 60) == now + timedelta(minutes=60)
    assert slots.earliest_bookable(now, 0) == now
