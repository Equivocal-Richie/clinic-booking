"""The showpiece: many clients race for the same slot; exactly one wins.

This is the heart of the assessment ("once booked, that slot must not be
available to others"). We fire N real concurrent booking attempts, each on its
own database session/connection, and assert that exactly one succeeds and the
rest receive a clean slot-taken conflict — proving the guarantee is enforced by
the database, not by luck or in-process coordination (which would not survive
the horizontally-scaled deployment this runs in).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlmodel import Session, select

from app.db import engine
from app.models import Appointment, AppointmentStatus
from app.services import booking
from app.services.exceptions import ConflictStateError, SlotTakenError

from .. import support

N = 20


def test_concurrent_bookings_only_one_succeeds(doctor, patient):
    slot = support.utc_slot(10, 0, weekday=0)
    now = slot - timedelta(days=1)

    def attempt(_: int) -> str:
        # Each thread uses its own session (and thus its own connection), the
        # way separate workers/instances would in production.
        with Session(engine) as s:
            try:
                booking.create_appointment(s, doctor.id, patient.id, slot, now)
                return "ok"
            except SlotTakenError:
                return "taken"

    with ThreadPoolExecutor(max_workers=N) as pool:
        results = list(pool.map(attempt, range(N)))

    assert results.count("ok") == 1, results
    assert results.count("taken") == N - 1

    # And the database holds exactly one active row for that slot.
    with Session(engine) as s:
        rows = s.exec(
            select(Appointment).where(
                Appointment.doctor_id == doctor.id,
                Appointment.start_at == slot,
                Appointment.status == AppointmentStatus.booked,
            )
        ).all()
    assert len(rows) == 1


def test_concurrent_cancels_only_one_succeeds(session, doctor, patient):
    """Cancel and reschedule take a row lock (SELECT ... FOR UPDATE), so racing
    cancels of one appointment serialize: exactly one succeeds and the rest get a
    clean 'already cancelled' conflict — no lost updates, no duplicate work."""
    slot = support.utc_slot(10, 0, weekday=0)
    now = slot - timedelta(days=1)
    appt = booking.create_appointment(session, doctor.id, patient.id, slot, now)
    appt_id = appt.id

    def attempt(_: int) -> str:
        with Session(engine) as s:
            try:
                booking.cancel_appointment(s, appt_id, "race", now)
                return "ok"
            except ConflictStateError:
                return "already"

    with ThreadPoolExecutor(max_workers=N) as pool:
        results = list(pool.map(attempt, range(N)))

    assert results.count("ok") == 1, results
    assert results.count("already") == N - 1
