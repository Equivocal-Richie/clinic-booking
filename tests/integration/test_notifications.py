"""Notification tasks: enqueue on book/cancel/reschedule, reminder scan, and SMTP gate.

Celery runs eagerly in tests (see conftest), so `.delay()` executes the task
synchronously. We patch the SMTP-sending function to record calls instead of
sending real mail.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session

from app.db import engine
from app.models import Appointment, AppointmentStatus
from app import tasks
from app.notifications import messages

from .. import support


@pytest.fixture
def sent(monkeypatch):
    """Record every email the tasks try to send (to, subject, body)."""
    records: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "app.notifications.email.send_email",
        lambda to, subject, body: records.append((to, subject, body)) or "sent",
    )
    return records


def _book(client, doctor_id, patient_id, slot):
    return client.post(
        "/appointments",
        json={"doctor_id": doctor_id, "patient_id": patient_id, "start_time": slot.isoformat()},
    )


def test_booking_enqueues_confirmation(client, doctor, patient, sent):
    slot = support.local_slot(9, 0, weekday=0)
    assert _book(client, doctor.id, patient.id, slot).status_code == 201
    assert len(sent) == 1
    to, subject, _ = sent[0]
    assert to == patient.email
    assert "confirmed" in subject.lower()


def test_cancel_enqueues_cancellation(client, doctor, patient, sent):
    slot = support.local_slot(10, 0, weekday=0)
    appt_id = _book(client, doctor.id, patient.id, slot).json()["id"]
    sent.clear()
    client.patch(f"/appointments/{appt_id}/cancel", json={"reason": "Feeling better"})
    assert len(sent) == 1
    _, subject, body = sent[0]
    assert "cancelled" in subject.lower()
    assert "Feeling better" in body


def test_reschedule_enqueues_notice_with_old_and_new(client, doctor, patient, sent):
    original = support.local_slot(9, 0, weekday=0)
    target = support.local_slot(11, 0, weekday=0)
    appt_id = _book(client, doctor.id, patient.id, original).json()["id"]
    sent.clear()
    r = client.patch(f"/appointments/{appt_id}/reschedule", json={"start_time": target.isoformat()})
    assert r.status_code == 200
    assert len(sent) == 1
    _, subject, body = sent[0]
    assert "rescheduled" in subject.lower()
    assert "Was:" in body and "Now:" in body


def test_reminder_scan_selects_due_dedupes_and_skips_far(session, doctor, patient, sent):
    now = datetime.now(timezone.utc)
    due = Appointment(doctor_id=doctor.id, patient_id=patient.id,
                      start_at=now + timedelta(hours=2), status=AppointmentStatus.booked)
    far = Appointment(doctor_id=doctor.id, patient_id=patient.id,
                      start_at=now + timedelta(days=3), status=AppointmentStatus.booked)
    session.add(due)
    session.add(far)
    session.commit()
    session.refresh(due)

    result = tasks.scan_and_send_reminders()
    assert result["reminders_processed"] == 1
    assert len(sent) == 1
    assert "reminder" in sent[0][1].lower()

    # Second scan: already-reminded appointment is not re-sent.
    sent.clear()
    result2 = tasks.scan_and_send_reminders()
    assert result2["reminders_processed"] == 0
    assert sent == []

    # The due appointment was stamped.
    with Session(engine) as s:
        assert s.get(Appointment, due.id).reminder_sent_at is not None


def test_message_builders_are_pure_and_localized():
    tz = support.CLINIC_TZ
    when = datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc)  # 09:00 Nairobi
    subject, body = messages.booking_confirmation("Jane", "Dr. Aisha", when, tz)
    assert "Dr. Aisha" in subject
    assert "Jane" in body
    assert "09:00 AM" in body  # rendered in clinic-local time


def test_send_email_disabled_is_noop(monkeypatch):
    # Default settings have notifications disabled -> SMTP must not be touched.
    import app.notifications.email as email_mod

    def _boom(*a, **k):
        raise AssertionError("SMTP should not be contacted when disabled")

    monkeypatch.setattr("smtplib.SMTP", _boom)
    assert email_mod.send_email("x@example.com", "s", "b") == "disabled"
