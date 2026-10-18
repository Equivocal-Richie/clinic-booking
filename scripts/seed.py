"""Seed the database with 5 doctors, their working hours, and a sample patient.

Idempotent: running it again does nothing if doctors already exist. Run with:
    python -m scripts.seed
"""
from __future__ import annotations

from datetime import time

from sqlmodel import Session, select

from app.db import engine
from app.models import Doctor, Patient, User, UserRole, WorkingHours
from app.security import hash_password

# Weekdays Monday(0)..Friday(4). Each doctor works 09:00-13:00 and 14:00-17:00
# (a lunch break modelled as two blocks). Doctor 5 also works Saturday mornings
# and one doctor starts later — just enough variety to exercise the logic.
WEEKDAYS = [0, 1, 2, 3, 4]

DOCTORS = [
    ("Dr. Aisha Mwangi", "General Practice", "standard"),
    ("Dr. Brian Otieno", "Pediatrics", "standard"),
    ("Dr. Carol Njoroge", "Dermatology", "standard"),
    ("Dr. David Kamau", "Cardiology", "late_start"),
    ("Dr. Esther Wanjiru", "Dentistry", "with_saturday"),
]


def _blocks_for(profile: str) -> list[tuple[int, time, time]]:
    blocks: list[tuple[int, time, time]] = []
    for d in WEEKDAYS:
        if profile == "late_start":
            blocks.append((d, time(11, 0), time(13, 0)))
            blocks.append((d, time(14, 0), time(18, 0)))
        else:
            blocks.append((d, time(9, 0), time(13, 0)))
            blocks.append((d, time(14, 0), time(17, 0)))
    if profile == "with_saturday":
        blocks.append((5, time(9, 0), time(12, 0)))  # Saturday morning
    return blocks


def seed() -> None:
    with Session(engine) as session:
        if session.exec(select(Doctor)).first() is not None:
            print("Doctors already present — skipping seed.")
            return

        for name, specialty, profile in DOCTORS:
            doctor = Doctor(name=name, specialty=specialty)
            session.add(doctor)
            session.flush()  # assign doctor.id
            for dow, start_t, end_t in _blocks_for(profile):
                session.add(
                    WorkingHours(
                        doctor_id=doctor.id,
                        day_of_week=dow,
                        start_time=start_t,
                        end_time=end_t,
                    )
                )

        # A sample patient with a login, and a clinical-staff login, so the
        # deployed API can be tried immediately. Change these in any real use.
        patient = Patient(name="Sample Patient", email="patient@example.com")
        session.add(patient)
        session.flush()
        session.add(
            User(
                email="patient@example.com",
                hashed_password=hash_password("patientpass123"),
                role=UserRole.patient,
                patient_id=patient.id,
            )
        )
        session.add(
            User(
                email="staff@clinic.test",
                hashed_password=hash_password("staffpass123"),
                role=UserRole.staff,
            )
        )
        session.commit()
        print(
            f"Seeded {len(DOCTORS)} doctors with working hours, "
            "1 patient login (patient@example.com / patientpass123), "
            "and 1 staff login (staff@clinic.test / staffpass123)."
        )


if __name__ == "__main__":
    seed()
