from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime

from pydantic import BaseModel


class Slot(BaseModel):
    start_time: datetime
    end_time: datetime


class AvailabilityResponse(BaseModel):
    doctor_id: int
    date: date_cls
    slot_duration_minutes: int
    available_slots: list[Slot]
