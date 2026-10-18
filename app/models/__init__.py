"""SQLModel table definitions."""
from .appointment import Appointment, AppointmentStatus
from .doctor import Doctor
from .idempotency import IdempotencyKey
from .patient import Patient
from .refresh_token import RefreshToken
from .user import User, UserRole
from .working_hours import WorkingHours

__all__ = [
    "Appointment",
    "AppointmentStatus",
    "Doctor",
    "IdempotencyKey",
    "Patient",
    "RefreshToken",
    "User",
    "UserRole",
    "WorkingHours",
]
