"""Celery tasks for booking notifications.

Tasks receive only JSON-serializable primitives (ids, ISO strings) and load the
rest from the database inside the worker — so task payloads stay small and never
carry ORM objects across the broker.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from .celery_app import celery_app
from .config import get_settings
from .db import engine
from .models import Appointment, AppointmentStatus, Doctor, Patient
from .notifications import email, messages


def _load(session: Session, appointment_id: int):
    appt = session.get(Appointment, appointment_id)
    if appt is None:
        return None
    patient = session.get(Patient, appt.patient_id)
    doctor = session.get(Doctor, appt.doctor_id)
    return appt, patient, doctor


@celery_app.task(name="app.tasks.send_booking_confirmation")
def send_booking_confirmation(appointment_id: int) -> str:
    settings = get_settings()
    with Session(engine) as s:
        loaded = _load(s, appointment_id)
        if loaded is None:
            return "appointment_not_found"
        appt, patient, doctor = loaded
        if not patient or not patient.email:
            return "no_recipient"
        subject, body = messages.booking_confirmation(
            patient.name, doctor.name, appt.start_at, settings.tz
        )
        return email.send_email(patient.email, subject, body)


@celery_app.task(name="app.tasks.send_cancellation")
def send_cancellation(appointment_id: int) -> str:
    settings = get_settings()
    with Session(engine) as s:
        loaded = _load(s, appointment_id)
        if loaded is None:
            return "appointment_not_found"
        appt, patient, doctor = loaded
        if not patient or not patient.email:
            return "no_recipient"
        subject, body = messages.cancellation(
            patient.name, doctor.name, appt.start_at, settings.tz, appt.cancellation_reason
        )
        return email.send_email(patient.email, subject, body)


@celery_app.task(name="app.tasks.send_reschedule")
def send_reschedule(appointment_id: int, old_start_iso: str) -> str:
    settings = get_settings()
    old_start = datetime.fromisoformat(old_start_iso)
    with Session(engine) as s:
        loaded = _load(s, appointment_id)
        if loaded is None:
            return "appointment_not_found"
        appt, patient, doctor = loaded
        if not patient or not patient.email:
            return "no_recipient"
        subject, body = messages.reschedule(
            patient.name, doctor.name, old_start, appt.start_at, settings.tz
        )
        return email.send_email(patient.email, subject, body)


@celery_app.task(name="app.tasks.scan_and_send_reminders")
def scan_and_send_reminders() -> dict:
    """Beat task: email reminders for appointments starting within the lead
    window that haven't been reminded yet, then mark them so we never re-send."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(minutes=settings.reminder_lead_minutes)
    processed = 0
    with Session(engine) as s:
        rows = s.exec(
            select(Appointment).where(
                Appointment.status == AppointmentStatus.booked,
                Appointment.reminder_sent_at.is_(None),  # type: ignore[union-attr]
                Appointment.start_at >= now,
                Appointment.start_at <= window_end,
            )
        ).all()
        for appt in rows:
            patient = s.get(Patient, appt.patient_id)
            doctor = s.get(Doctor, appt.doctor_id)
            if patient and patient.email and doctor:
                subject, body = messages.reminder(
                    patient.name, doctor.name, appt.start_at, settings.tz
                )
                email.send_email(patient.email, subject, body)
            appt.reminder_sent_at = now
            s.add(appt)
            processed += 1
        s.commit()
    return {"reminders_processed": processed}
