from __future__ import annotations

from sqlmodel import Field, SQLModel


class Doctor(SQLModel, table=True):
    __tablename__ = "doctors"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    specialty: str | None = Field(default=None)
