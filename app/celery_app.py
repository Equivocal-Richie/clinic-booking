"""Celery application for asynchronous notifications.

JSON serializer only (never pickle — pickle deserialization is an RCE vector).
The beat schedule periodically scans for appointments that are due a reminder.
"""
from __future__ import annotations

from celery import Celery

from .config import get_settings

_settings = get_settings()

celery_app = Celery(
    "clinic",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "scan-reminders": {
            "task": "app.tasks.scan_and_send_reminders",
            "schedule": float(_settings.reminder_scan_interval_minutes * 60),
        }
    },
)
