from __future__ import annotations

from datetime import time

from sqlmodel import Field, SQLModel


class WorkingHours(SQLModel, table=True):
    """A block of working time for a doctor on a given weekday.

    Multiple rows are allowed per (doctor, weekday) so that breaks (e.g. lunch)
    are modelled simply as two separate blocks: 09:00-13:00 and 14:00-17:00.
    Times are wall-clock in the clinic timezone (see settings.clinic_timezone).
    """

    __tablename__ = "working_hours"

    id: int | None = Field(default=None, primary_key=True)
    doctor_id: int = Field(foreign_key="doctors.id", index=True)
    # Python convention: Monday=0 ... Sunday=6 (matches datetime.weekday()).
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
