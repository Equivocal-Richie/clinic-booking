"""Pytest fixtures.

Schema is built by running the real Alembic migrations against the test
database at session start, so every test run also verifies that migrations
apply cleanly (and that the partial unique index is created). Tables are
truncated between tests for isolation.
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

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Doctor, Patient, WorkingHours  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TABLES = ["appointments", "working_hours", "patients", "doctors"]


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
def client():
    return TestClient(app)


@pytest.fixture
def doctor(session) -> Doctor:
    """A doctor working Mon-Fri, 09:00-13:00 and 14:00-17:00 (lunch break)."""
    doc = Doctor(name="Dr. Test", specialty="General")
    session.add(doc)
    session.flush()
    for dow in range(0, 5):  # Mon..Fri
        session.add(
            WorkingHours(
                doctor_id=doc.id, day_of_week=dow,
                start_time=time(9, 0), end_time=time(13, 0),
            )
        )
        session.add(
            WorkingHours(
                doctor_id=doc.id, day_of_week=dow,
                start_time=time(14, 0), end_time=time(17, 0),
            )
        )
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
