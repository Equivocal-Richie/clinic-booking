"""Pure slot-grid logic.

This module is deliberately free of any database or web dependency: every
function takes plain values and returns plain values, so the booking rules can
be unit-tested exhaustively and fast. The DB-facing wrappers live in
availability.py.

Core idea: availability is DERIVED, never stored. We never pre-generate a row
per slot. The grid of candidate slots is computed on demand from a doctor's
working-hours blocks; actual availability is that grid minus already-booked
starts, minus anything too soon to book.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def generate_grid(
    blocks: list[tuple[time, time]],
    on_date: date_cls,
    tz: ZoneInfo,
    duration_minutes: int,
) -> list[datetime]:
    """Expand working-hour blocks for one day into UTC slot-start datetimes.

    - blocks are (start_time, end_time) wall-clock pairs in `tz`.
    - A slot is only emitted if the FULL duration fits before the block end,
      so a block ending 17:00 yields a last 30-min slot starting 16:30.
    - Overlapping/duplicate blocks are de-duplicated.
    - Result is sorted ascending and timezone-aware in UTC.
    """
    step = timedelta(minutes=duration_minutes)
    starts: set[datetime] = set()
    for start_t, end_t in blocks:
        cursor = datetime.combine(on_date, start_t, tzinfo=tz)
        block_end = datetime.combine(on_date, end_t, tzinfo=tz)
        while cursor + step <= block_end:
            starts.add(cursor.astimezone(timezone.utc))
            cursor += step
    return sorted(starts)


def earliest_bookable(now: datetime, min_lead_minutes: int) -> datetime:
    """The earliest start time that may be booked, given the lead-time rule."""
    return now + timedelta(minutes=min_lead_minutes)


def available_slots(
    grid: list[datetime],
    booked_starts: set[datetime],
    now: datetime,
    min_lead_minutes: int,
) -> list[datetime]:
    """Grid minus booked starts, minus anything earlier than the lead cutoff.

    Keeping this filter here (and reusing it for both GET availability and the
    booking validation) guarantees the two can never disagree about whether a
    slot is bookable.
    """
    cutoff = earliest_bookable(now, min_lead_minutes)
    booked = set(booked_starts)
    return [s for s in grid if s not in booked and s >= cutoff]
