"""Enqueue notification tasks from request handlers, resiliently.

A broker outage must never fail a booking, so enqueue errors are swallowed and
logged — the booking already succeeded; only the email is best-effort.
"""
from __future__ import annotations

import logging

from .. import tasks

logger = logging.getLogger(__name__)


def _safe_delay(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception as exc:  # noqa: BLE001 — notifications are best-effort
        logger.warning("Failed to enqueue %s: %s", getattr(task, "name", task), exc)


def on_booking_created(appointment_id: int) -> None:
    _safe_delay(tasks.send_booking_confirmation, appointment_id)


def on_cancelled(appointment_id: int) -> None:
    _safe_delay(tasks.send_cancellation, appointment_id)


def on_rescheduled(appointment_id: int, old_start_iso: str) -> None:
    _safe_delay(tasks.send_reschedule, appointment_id, old_start_iso)
