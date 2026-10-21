"""Pytest fixtures.

Schema is built by running the real Alembic migrations against the test
database at session start, so every run also verifies migrations apply cleanly.
Tables are truncated between tests for isolation.

Rate limiting is disabled for the main suite (so repeated test requests don't
trip limits); it is tested in isolation in test_rate_limit.py.
"""
from __future__ import annotations

import os
from datetime import time

# Must be set BEFORE importing the app so settings/engine bind to the test DB.
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://postgres@localhost:5432/clinic_test",
    ),
)
os.environ.setdefault("CLINIC_TIMEZONE", "Africa/Nairobi")
os.environ.setdefault("MIN_LEAD_MINUTES", "60")
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-bytes-long-000")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.celery_app import celery_app  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Doctor, Patient, User, UserRole, WorkingHours  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402

# Run Celery tasks synchronously in-process during tests (no broker needed).
celery_app.conf.task_always_eager = True
celery_app.conf.task_eager_propagates = True

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TABLES = ["idempotency_keys", "refresh_tokens", "appointments", "working_hours", "users", "patients", "doctors"]


@pytest.fixture(scope="session", autouse=True)
def _prepare_schema():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(os.path.join(_REPO_ROOT, "alembic.ini"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE")
        )
    yield


@pytest.fixture
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture
def doctor(session) -> Doctor:
    """A doctor working Mon-Fri, 09:00-13:00 and 14:00-17:00 (lunch break)."""
    doc = Doctor(name="Dr. Test", specialty="General")
    session.add(doc)
    session.flush()
    for dow in range(0, 5):
        session.add(WorkingHours(doctor_id=doc.id, day_of_week=dow, start_time=time(9, 0), end_time=time(13, 0)))
        session.add(WorkingHours(doctor_id=doc.id, day_of_week=dow, start_time=time(14, 0), end_time=time(17, 0)))
    session.commit()
    session.refresh(doc)
    return doc


@pytest.fixture
def patient(session) -> Patient:
    p = Patient(name="Test Patient", email="p@example.com")
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@pytest.fixture
def patient_user(session, patient) -> User:
    u = User(
        email="p@example.com",
        hashed_password=hash_password("patientpass123"),
        role=UserRole.patient,
        patient_id=patient.id,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@pytest.fixture
def staff_user(session) -> User:
    u = User(
        email="staff@clinic.test",
        hashed_password=hash_password("staffpass123"),
        role=UserRole.staff,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role.value)}"}


@pytest.fixture
def anon_client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def client(staff_user) -> TestClient:
    """Authenticated as clinical staff (can act across all patients)."""
    return TestClient(app, headers=_auth_headers(staff_user))


@pytest.fixture
def patient_client(patient_user) -> TestClient:
    """Authenticated as the seeded patient (can act only on their own data)."""
    return TestClient(app, headers=_auth_headers(patient_user))
