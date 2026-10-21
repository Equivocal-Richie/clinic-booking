"""Pure builders for notification subject/body text.

No I/O here, so the wording is trivially unit-testable. All datetimes are UTC in
and are rendered in the clinic timezone for the reader.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_FMT = "%A, %d %b %Y at %I:%M %p %Z"


def format_local(when_utc: datetime, tz: ZoneInfo) -> str:
    if when_utc.tzinfo is None:
        when_utc = when_utc.replace(tzinfo=timezone.utc)
    return when_utc.astimezone(tz).strftime(_FMT)


def booking_confirmation(
    patient_name: str, doctor_name: str, when_utc: datetime, tz: ZoneInfo
) -> tuple[str, str]:
    when = format_local(when_utc, tz)
    subject = f"Appointment confirmed with {doctor_name}"
    body = (
        f"Hi {patient_name},\n\n"
        f"Your appointment with {doctor_name} is confirmed for {when}.\n\n"
        f"If you need to cancel or reschedule, please use the booking system.\n\n"
        f"— Clinic Booking"
    )
    return subject, body


def cancellation(
    patient_name: str, doctor_name: str, when_utc: datetime, tz: ZoneInfo, reason: str | None
) -> tuple[str, str]:
    when = format_local(when_utc, tz)
    subject = f"Appointment cancelled with {doctor_name}"
    reason_line = f"\nReason: {reason}\n" if reason else "\n"
    body = (
        f"Hi {patient_name},\n\n"
        f"Your appointment with {doctor_name} on {when} has been cancelled.{reason_line}\n"
        f"You can book a new slot any time.\n\n"
        f"— Clinic Booking"
    )
    return subject, body


def reschedule(
    patient_name: str,
    doctor_name: str,
    old_when_utc: datetime,
    new_when_utc: datetime,
    tz: ZoneInfo,
) -> tuple[str, str]:
    old = format_local(old_when_utc, tz)
    new = format_local(new_when_utc, tz)
    subject = f"Appointment rescheduled with {doctor_name}"
    body = (
        f"Hi {patient_name},\n\n"
        f"Your appointment with {doctor_name} has been moved.\n"
        f"Was: {old}\nNow: {new}\n\n"
        f"— Clinic Booking"
    )
    return subject, body


def reminder(
    patient_name: str, doctor_name: str, when_utc: datetime, tz: ZoneInfo
) -> tuple[str, str]:
    when = format_local(when_utc, tz)
    subject = f"Reminder: appointment with {doctor_name}"
    body = (
        f"Hi {patient_name},\n\n"
        f"This is a reminder of your upcoming appointment with {doctor_name} on {when}.\n\n"
        f"— Clinic Booking"
    )
    return subject, body
