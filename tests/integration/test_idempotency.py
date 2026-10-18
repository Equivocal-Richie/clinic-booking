"""Idempotency-Key behaviour on POST /appointments."""
from __future__ import annotations

from .. import support


def test_same_key_same_body_replays_original_response(client, doctor, patient):
    slot = support.local_slot(9, 0, weekday=0)
    body = {"doctor_id": doctor.id, "patient_id": patient.id, "start_time": slot.isoformat()}
    headers = {"Idempotency-Key": "booking-abc-123"}

    r1 = client.post("/appointments", json=body, headers=headers)
    r2 = client.post("/appointments", json=body, headers=headers)

    assert r1.status_code == 201
    assert r2.status_code == 201
    # Same appointment returned, not a second booking nor a 409.
    assert r1.json()["id"] == r2.json()["id"]

    items = client.get(f"/patients/{patient.id}/appointments").json()["items"]
    assert len(items) == 1


def test_without_key_duplicate_is_a_conflict(client, doctor, patient):
    slot = support.local_slot(10, 0, weekday=0)
    body = {"doctor_id": doctor.id, "patient_id": patient.id, "start_time": slot.isoformat()}
    assert client.post("/appointments", json=body).status_code == 201
    # No idempotency key -> the duplicate hits the slot guard.
    assert client.post("/appointments", json=body).status_code == 409


def test_key_reuse_with_different_body_is_rejected(client, doctor, patient):
    headers = {"Idempotency-Key": "reused-key"}
    s1 = support.local_slot(9, 0, weekday=0)
    s2 = support.local_slot(10, 0, weekday=0)
    assert client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": patient.id, "start_time": s1.isoformat()},
        headers=headers,
    ).status_code == 201
    r = client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": patient.id, "start_time": s2.isoformat()},
        headers=headers,
    )
    assert r.status_code == 422


def test_key_released_after_failed_attempt_allows_retry(client, doctor, patient):
    # First attempt fails validation (past/off-grid): key should be released so a
    # corrected retry with the same key can succeed.
    headers = {"Idempotency-Key": "retry-key"}
    bad = client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": patient.id, "start_time": support.local_slot(9, 15, weekday=0).isoformat()},
        headers=headers,
    )
    assert bad.status_code == 400
    good = client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": patient.id, "start_time": support.local_slot(9, 0, weekday=0).isoformat()},
        headers=headers,
    )
    assert good.status_code == 201
