"""DB-facing availability logic — thin wrappers over the pure core in slots.py."""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time, timedelta, timezone

from sqlmodel import Session, select

from ..models import Appointment, AppointmentStatus, Doctor, WorkingHours
from . import slots
from .config_access import get_runtime
from .exceptions import NotFoundError


def _blocks_for(session: Session, doctor_id: int, weekday: int) -> list[tuple[time, time]]:
    rows = session.exec(
        select(WorkingHours).where(
            WorkingHours.doctor_id == doctor_id,
            WorkingHours.day_of_week == weekday,
        )
    ).all()
    return [(r.start_time, r.end_time) for r in rows]


def require_doctor(session: Session, doctor_id: int) -> Doctor:
    doctor = session.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError(f"Doctor {doctor_id} does not exist")
    return doctor


def grid_for(session: Session, doctor_id: int, on_date: date_cls) -> list[datetime]:
    """All candidate slot starts (UTC) for a doctor on a date, ignoring bookings."""
    tz, duration, _lead = get_runtime()
    weekday = on_date.weekday()
    blocks = _blocks_for(session, doctor_id, weekday)
    return slots.generate_grid(blocks, on_date, tz, duration)


def _booked_starts_on(
    session: Session, doctor_id: int, on_date: date_cls
) -> set[datetime]:
    """Start times of active (booked) appointments for a doctor on a date.

    We query a UTC day-window that safely covers the local day (plus margin for
    the clinic's UTC offset), then intersect with the grid, so timezone offset
    never causes a slot to be missed.
    """
    tz, _duration, _lead = get_runtime()
    day_start_local = datetime.combine(on_date, time.min, tzinfo=tz)
    window_start = (day_start_local - timedelta(days=1)).astimezone(timezone.utc)
    window_end = (day_start_local + timedelta(days=2)).astimezone(timezone.utc)
    rows = session.exec(
        select(Appointment.start_at).where(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.booked,
            Appointment.start_at >= window_start,
            Appointment.start_at < window_end,
        )
    ).all()
    return {r if r.tzinfo else r.replace(tzinfo=timezone.utc) for r in rows}


def compute_availability(
    session: Session, doctor_id: int, on_date: date_cls, now: datetime
) -> list[datetime]:
    """Available slot starts (UTC): grid - booked - too-soon. Raises if no doctor."""
    require_doctor(session, doctor_id)
    _tz, _duration, lead = get_runtime()
    grid = grid_for(session, doctor_id, on_date)
    booked = _booked_starts_on(session, doctor_id, on_date)
    return slots.available_slots(grid, booked, now, lead)
