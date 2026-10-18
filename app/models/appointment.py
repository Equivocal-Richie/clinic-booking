from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel


class AppointmentStatus(str, enum.Enum):
    booked = "booked"
    cancelled = "cancelled"
    completed = "completed"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Appointment(SQLModel, table=True):
    __tablename__ = "appointments"
    __table_args__ = (
        # THE concurrency guarantee. A partial UNIQUE index means the database
        # itself forbids two *active* (booked) appointments for the same doctor
        # at the same start time — regardless of how many app instances or
        # workers race. Cancelled/completed rows are excluded from the index,
        # so a slot freed by a cancellation becomes bookable again without
        # deleting history. Two concurrent inserts for the same slot: exactly
        # one commits, the other raises IntegrityError -> mapped to 409.
        Index(
            "uq_active_appointment_slot",
            "doctor_id",
            "start_at",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    doctor_id: int = Field(foreign_key="doctors.id", index=True)
    patient_id: int = Field(foreign_key="patients.id", index=True)

    # Always stored timezone-aware in UTC. Duration kept explicit so slot length
    # can evolve ("we want to grow") without a schema change.
    start_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    duration_minutes: int = Field(default=30)

    # VARCHAR + CHECK (native_enum=False) rather than a native PG enum type:
    # keeps the partial-index predicate ("status = 'booked'") trivial and avoids
    # enum-migration friction as statuses grow.
    status: AppointmentStatus = Field(
        default=AppointmentStatus.booked,
        sa_column=Column(
            SAEnum(AppointmentStatus, native_enum=False, length=20),
            nullable=False,
            index=True,
        ),
    )
    cancellation_reason: str | None = Field(default=None)

    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
