"""SMTP email delivery (Gmail-compatible), gated by settings.

Delivery is a no-op unless NOTIFICATIONS_ENABLED is true, so dev and tests never
send real mail. If NOTIFY_OVERRIDE_EMAIL is set, every message is redirected
there — useful for testing a live SMTP setup without emailing real patients.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import get_settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> str:
    """Send one plain-text email. Returns a short status string (also logged).

    Never raises on an SMTP failure — notifications must not take down the
    worker task; the failure is logged and the task result records it.
    """
    settings = get_settings()
    recipient = settings.notify_override_email or to

    if not settings.notifications_enabled:
        logger.info("Notifications disabled; would have emailed %s: %s", recipient, subject)
        return "disabled"

    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
        logger.info("Sent email to %s: %s", recipient, subject)
        return "sent"
    except Exception as exc:  # noqa: BLE001 — notifications are best-effort
        logger.warning("Failed to send email to %s: %s", recipient, exc)
        return f"error: {exc}"
