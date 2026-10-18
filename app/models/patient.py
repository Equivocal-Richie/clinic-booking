from __future__ import annotations

from sqlmodel import Field, SQLModel


class Patient(SQLModel, table=True):
    __tablename__ = "patients"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str | None = Field(default=None)
    phone: str | None = Field(default=None)
