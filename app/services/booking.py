"""Booking operations: create, cancel, reschedule, and patient lookups.

All validation for "is this slot bookable?" funnels through `validate_slot`, so
the availability endpoint and the booking endpoints can never diverge on the
rules. The database partial unique index is the final arbiter of slot
exclusivity under concurrency; this layer maps its IntegrityError to a clean
409.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..models import Appointment, AppointmentStatus, Patient
from . import availability
from .config_access import get_runtime
from .exceptions import (
    ConflictStateError,
    NotFoundError,
    SlotTakenError,
    ValidationError,
)


def _require_patient(session: Session, patient_id: int) -> Patient:
    patient = session.get(Patient, patient_id)
    if patient is None:
        raise NotFoundError(f"Patient {patient_id} does not exist")
    return patient


def _require_appointment(session: Session, appointment_id: int) -> Appointment:
    appt = session.get(Appointment, appointment_id)
    if appt is None:
        raise NotFoundError(f"Appointment {appointment_id} does not exist")
    return appt


def validate_slot(
    session: Session, doctor_id: int, start_at_utc: datetime, now: datetime
) -> None:
    """Raise a ValidationError unless start_at_utc is a bookable slot.

    Checks, in order, to produce the most helpful message:
      1. doctor exists (NotFoundError)
      2. the doctor works that day at all
      3. start is a real 30-min grid slot within working hours (alignment +
         within-hours + correct weekday are all covered by grid membership)
      4. start is not in the past
      5. start respects the lead-time rule
    Slot-taken is NOT checked here — that is enforced atomically by the DB on
    insert/update, which is the only race-free place to check it.
    """
    availability.require_doctor(session, doctor_id)
    _tz, _duration, lead = get_runtime()

    on_date = start_at_utc.astimezone(_tz).date()
    grid = availability.grid_for(session, doctor_id, on_date)

    if not grid:
        raise ValidationError(
            f"Doctor {doctor_id} has no working hours on {on_date.isoformat()}"
        )
    if start_at_utc not in set(grid):
        raise ValidationError(
            "start_time is not a valid slot within the doctor's working hours "
            "(must align to a 30-minute slot inside working hours on a working day)"
        )
    if start_at_utc < now:
        raise ValidationError("Cannot book a slot in the past")
    if lead > 0 and start_at_utc < now + timedelta(minutes=lead):
        raise ValidationError(
            f"Bookings must be made at least {lead} minutes in advance"
        )


def create_appointment(
    session: Session,
    doctor_id: int,
    patient_id: int,
    start_at_utc: datetime,
    now: datetime,
) -> Appointment:
    availability.require_doctor(session, doctor_id)
    _require_patient(session, patient_id)
    validate_slot(session, doctor_id, start_at_utc, now)

    _tz, duration, _lead = get_runtime()
    appt = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        start_at=start_at_utc,
        duration_minutes=duration,
        status=AppointmentStatus.booked,
    )
    session.add(appt)
    try:
        session.commit()
    except IntegrityError:
        # The partial unique index rejected a concurrent/duplicate booking.
        session.rollback()
        raise SlotTakenError("That slot has just been booked by someone else")
    session.refresh(appt)
    return appt


def cancel_appointment(
    session: Session, appointment_id: int, reason: str, now: datetime
) -> Appointment:
    appt = _require_appointment(session, appointment_id)
    if appt.status == AppointmentStatus.cancelled:
        raise ConflictStateError("Appointment is already cancelled")

    appt.status = AppointmentStatus.cancelled
    appt.cancellation_reason = reason
    appt.updated_at = now
    session.add(appt)
    session.commit()
    session.refresh(appt)
    return appt


def reschedule_appointment(
    session: Session, appointment_id: int, new_start_at_utc: datetime, now: datetime
) -> Appointment:
    appt = _require_appointment(session, appointment_id)
    if appt.status == AppointmentStatus.cancelled:
        raise ConflictStateError("Cannot reschedule a cancelled appointment")

    # Validate the destination exactly as a fresh booking would be validated.
    validate_slot(session, appt.doctor_id, new_start_at_utc, now)

    # Moving the same row to a new start: the original slot is freed atomically
    # (same row changes start_at) and the partial unique index rejects the move
    # if the destination is already taken by a different active appointment.
    appt.start_at = new_start_at_utc
    appt.updated_at = now
    session.add(appt)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise SlotTakenError("The target slot is already booked")
    session.refresh(appt)
    return appt


def upcoming_for_patient(
    session: Session,
    patient_id: int,
    now: datetime,
    limit: int,
    offset: int,
) -> tuple[list[Appointment], bool]:
    """A patient's upcoming booked appointments, soonest first, paginated.

    Uses an indexed ORDER BY start_at with LIMIT/OFFSET and the "fetch one extra"
    trick to report has_more without a COUNT(*). Returns (items, has_more).
    """
    _require_patient(session, patient_id)
    rows = session.exec(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.status == AppointmentStatus.booked,
            Appointment.start_at >= now,
        )
        .order_by(Appointment.start_at)
        .offset(offset)
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    # Normalise tzinfo for any driver that returns naive UTC.
    for r in rows:
        if r.start_at.tzinfo is None:
            r.start_at = r.start_at.replace(tzinfo=timezone.utc)
    return list(rows), has_more
