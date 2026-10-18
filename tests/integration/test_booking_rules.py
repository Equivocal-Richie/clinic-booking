"""Service-layer booking validation (deterministic injected clock)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.services import booking
from app.services.exceptions import NotFoundError, ValidationError

from .. import support


def test_book_valid_slot_succeeds(session, doctor, patient):
    slot = support.utc_slot(9, 0, weekday=0)
    now = slot - timedelta(days=1)
    appt = booking.create_appointment(session, doctor.id, patient.id, slot, now)
    assert appt.id is not None
    assert appt.start_at == slot


def test_book_in_the_past_is_rejected(session, doctor, patient):
    slot = support.utc_slot(9, 0, weekday=0)
    now = slot + timedelta(hours=1)  # slot already elapsed
    with pytest.raises(ValidationError, match="past"):
        booking.create_appointment(session, doctor.id, patient.id, slot, now)


def test_misaligned_start_is_rejected(session, doctor, patient):
    slot = support.utc_slot(9, 15, weekday=0)  # not on a 30-min boundary
    now = slot - timedelta(days=1)
    with pytest.raises(ValidationError, match="valid slot"):
        booking.create_appointment(session, doctor.id, patient.id, slot, now)


def test_outside_working_hours_is_rejected(session, doctor, patient):
    slot = support.utc_slot(8, 0, weekday=0)  # before 09:00
    now = slot - timedelta(days=1)
    with pytest.raises(ValidationError, match="valid slot"):
        booking.create_appointment(session, doctor.id, patient.id, slot, now)


def test_lunch_break_slot_is_rejected(session, doctor, patient):
    slot = support.utc_slot(13, 0, weekday=0)  # inside the lunch gap
    now = slot - timedelta(days=1)
    with pytest.raises(ValidationError, match="valid slot"):
        booking.create_appointment(session, doctor.id, patient.id, slot, now)


def test_non_working_day_is_rejected(session, doctor, patient):
    slot = support.utc_slot(9, 0, weekday=5)  # Saturday
    now = slot - timedelta(days=1)
    with pytest.raises(ValidationError, match="no working hours"):
        booking.create_appointment(session, doctor.id, patient.id, slot, now)


def test_lead_time_rule_is_enforced(session, doctor, patient):
    slot = support.utc_slot(9, 0, weekday=0)
    now = slot - timedelta(minutes=30)  # within the 60-min lead window
    with pytest.raises(ValidationError, match="at least 60 minutes"):
        booking.create_appointment(session, doctor.id, patient.id, slot, now)


def test_unknown_doctor_or_patient(session, doctor, patient):
    slot = support.utc_slot(9, 0, weekday=0)
    now = slot - timedelta(days=1)
    with pytest.raises(NotFoundError):
        booking.create_appointment(session, 9999, patient.id, slot, now)
    with pytest.raises(NotFoundError):
        booking.create_appointment(session, doctor.id, 9999, slot, now)
