from __future__ import annotations

import enum

from sqlmodel import Field, SQLModel


class UserRole(str, enum.Enum):
    patient = "patient"
    staff = "staff"


class User(SQLModel, table=True):
    """An authenticatable account.

    A `patient` user is linked to a Patient row via patient_id (so a patient can
    only ever act on their own appointments). A `staff` user (clinical staff /
    reception) has patient_id = NULL and may act across all patients.
    """

    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    role: UserRole = Field(default=UserRole.patient, index=True)
    patient_id: int | None = Field(default=None, foreign_key="patients.id", index=True)
    is_active: bool = Field(default=True)
