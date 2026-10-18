from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from ..models import UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    id: int
    email: EmailStr
    role: UserRole
    patient_id: int | None = None


class PatientRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1)
    phone: str | None = None


class StaffCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
