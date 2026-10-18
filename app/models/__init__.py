"""SQLModel table definitions."""
from .appointment import Appointment, AppointmentStatus
from .doctor import Doctor
from .patient import Patient
from .working_hours import WorkingHours

__all__ = [
    "Appointment",
    "AppointmentStatus",
    "Doctor",
    "Patient",
    "WorkingHours",
]
