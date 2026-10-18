"""Authentication and role-based access control."""
from __future__ import annotations

from .. import support


def test_unauthenticated_requests_are_rejected(anon_client, doctor):
    assert anon_client.get(
        f"/doctors/{doctor.id}/availability", params={"date": "2026-10-19"}
    ).status_code == 401
    assert anon_client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": 1, "start_time": "2026-10-26T09:00:00+03:00"},
    ).status_code == 401


def test_register_then_login_flow(anon_client):
    reg = anon_client.post(
        "/auth/register",
        json={"email": "newpatient@example.com", "password": "securepass1", "name": "New Patient"},
    )
    assert reg.status_code == 201
    assert reg.json()["role"] == "patient"
    assert reg.json()["patient_id"] is not None

    login = anon_client.post(
        "/auth/login",
        data={"username": "newpatient@example.com", "password": "securepass1"},
    )
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    assert login.json()["access_token"]


def test_register_duplicate_email_conflicts(anon_client):
    body = {"email": "dup@example.com", "password": "securepass1", "name": "Dup"}
    assert anon_client.post("/auth/register", json=body).status_code == 201
    assert anon_client.post("/auth/register", json=body).status_code == 409


def test_login_wrong_password_401(anon_client, patient_user):
    r = anon_client.post(
        "/auth/login", data={"username": patient_user.email, "password": "wrong"}
    )
    assert r.status_code == 401


def test_patient_can_book_for_self(patient_client, doctor, patient):
    slot = support.local_slot(9, 0, weekday=0)
    r = patient_client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": patient.id, "start_time": slot.isoformat()},
    )
    assert r.status_code == 201


def test_patient_cannot_book_for_another_patient(patient_client, doctor, session):
    from app.models import Patient

    other = Patient(name="Someone Else")
    session.add(other)
    session.commit()
    session.refresh(other)
    slot = support.local_slot(10, 0, weekday=0)
    r = patient_client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": other.id, "start_time": slot.isoformat()},
    )
    assert r.status_code == 403


def test_patient_cannot_view_another_patients_appointments(patient_client, patient):
    other_id = patient.id + 999
    r = patient_client.get(f"/patients/{other_id}/appointments")
    assert r.status_code == 403


def test_staff_can_view_any_patient(client, patient):
    r = client.get(f"/patients/{patient.id}/appointments")
    assert r.status_code == 200


def test_patient_cannot_create_staff(patient_client):
    r = patient_client.post(
        "/auth/staff", json={"email": "sneaky@example.com", "password": "password12"}
    )
    assert r.status_code == 403


def test_staff_can_create_staff(client):
    r = client.post(
        "/auth/staff", json={"email": "newstaff@example.com", "password": "password12"}
    )
    assert r.status_code == 201
    assert r.json()["role"] == "staff"


def test_patient_cannot_cancel_another_patients_appointment(
    client, patient_client, doctor, patient, session
):
    # Staff books for a DIFFERENT patient; our patient must not be able to cancel it.
    from app.models import Patient

    other = Patient(name="Other")
    session.add(other)
    session.commit()
    session.refresh(other)
    slot = support.local_slot(11, 0, weekday=0)
    appt_id = client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": other.id, "start_time": slot.isoformat()},
    ).json()["id"]

    r = patient_client.patch(f"/appointments/{appt_id}/cancel", json={"reason": "no"})
    assert r.status_code == 403
