from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, computed_field

from ..models import AppointmentStatus


class AppointmentCreate(BaseModel):
    doctor_id: int = Field(gt=0)
    patient_id: int = Field(gt=0)
    # Accepts ISO 8601. If no offset is supplied it is interpreted as
    # clinic-local time (see services.timeutils.to_utc).
    start_time: datetime = Field(
        description="Slot start. ISO 8601; naive values are treated as clinic-local.",
        examples=["2026-10-20T09:00:00+03:00"],
    )


class RescheduleRequest(BaseModel):
    start_time: datetime = Field(examples=["2026-10-20T10:30:00+03:00"])


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500, examples=["Patient unwell"])


class PaginatedAppointments(BaseModel):
    items: list["AppointmentRead"]
    limit: int
    offset: int
    has_more: bool


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    patient_id: int
    start_time: datetime = Field(validation_alias="start_at")
    duration_minutes: int
    status: AppointmentStatus
    cancellation_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def end_time(self) -> datetime:
        start = self.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return start + timedelta(minutes=self.duration_minutes)


# Resolve the forward reference in PaginatedAppointments now AppointmentRead exists.
PaginatedAppointments.model_rebuild()
