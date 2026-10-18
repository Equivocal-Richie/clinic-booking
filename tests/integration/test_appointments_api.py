"""End-to-end HTTP tests for booking, cancel, reschedule, and the bonus list."""
from __future__ import annotations

from datetime import datetime, timezone

from .. import support


def _book(client, doctor_id, patient_id, slot_local):
    return client.post(
        "/appointments",
        json={
            "doctor_id": doctor_id,
            "patient_id": patient_id,
            "start_time": slot_local.isoformat(),
        },
    )


def test_book_returns_201_with_expected_fields(client, doctor, patient):
    slot = support.local_slot(9, 0, weekday=0)
    r = _book(client, doctor.id, patient.id, slot)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "booked"
    assert body["duration_minutes"] == 30
    assert datetime.fromisoformat(body["start_time"]) == slot.astimezone(timezone.utc)
    # end_time is start + 30 min.
    assert (
        datetime.fromisoformat(body["end_time"])
        - datetime.fromisoformat(body["start_time"])
    ).total_seconds() == 1800


def test_double_booking_same_slot_returns_409(client, doctor, patient):
    slot = support.local_slot(10, 0, weekday=0)
    assert _book(client, doctor.id, patient.id, slot).status_code == 201
    second = _book(client, doctor.id, patient.id, slot)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "slot_taken"


def test_cancel_frees_slot_and_allows_rebooking(client, doctor, patient):
    slot = support.local_slot(11, 0, weekday=0)
    appt_id = _book(client, doctor.id, patient.id, slot).json()["id"]

    cancelled = client.patch(
        f"/appointments/{appt_id}/cancel", json={"reason": "Patient unwell"}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancellation_reason"] == "Patient unwell"

    # Slot is bookable again (partial index excludes cancelled rows).
    rebooked = _book(client, doctor.id, patient.id, slot)
    assert rebooked.status_code == 201


def test_cancel_already_cancelled_returns_409(client, doctor, patient):
    slot = support.local_slot(9, 30, weekday=0)
    appt_id = _book(client, doctor.id, patient.id, slot).json()["id"]
    client.patch(f"/appointments/{appt_id}/cancel", json={"reason": "x"})
    again = client.patch(f"/appointments/{appt_id}/cancel", json={"reason": "y"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"


def test_cancel_unknown_returns_404(client):
    r = client.patch("/appointments/999/cancel", json={"reason": "x"})
    assert r.status_code == 404


def test_cancel_requires_reason(client, doctor, patient):
    slot = support.local_slot(14, 0, weekday=0)
    appt_id = _book(client, doctor.id, patient.id, slot).json()["id"]
    r = client.patch(f"/appointments/{appt_id}/cancel", json={"reason": ""})
    assert r.status_code == 422  # schema validation (min_length)


def test_reschedule_moves_slot_and_frees_original(client, doctor, patient):
    original = support.local_slot(9, 0, weekday=0)
    target = support.local_slot(10, 0, weekday=0)
    appt_id = _book(client, doctor.id, patient.id, original).json()["id"]

    r = client.patch(
        f"/appointments/{appt_id}/reschedule", json={"start_time": target.isoformat()}
    )
    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["start_time"]) == target.astimezone(timezone.utc)

    # Original slot is now bookable again; target is taken.
    assert _book(client, doctor.id, patient.id, original).status_code == 201
    assert _book(client, doctor.id, patient.id, target).status_code == 409


def test_reschedule_to_taken_slot_returns_409_and_keeps_original(client, doctor, patient):
    slot_a = support.local_slot(9, 0, weekday=0)
    slot_b = support.local_slot(9, 30, weekday=0)
    appt_a = _book(client, doctor.id, patient.id, slot_a).json()["id"]
    _book(client, doctor.id, patient.id, slot_b)

    r = client.patch(
        f"/appointments/{appt_a}/reschedule", json={"start_time": slot_b.isoformat()}
    )
    assert r.status_code == 409
    # Original appointment unchanged (still at slot_a).
    detail = client.get(f"/patients/{patient.id}/appointments").json()
    a_start = next(a["start_time"] for a in detail if a["id"] == appt_a)
    assert datetime.fromisoformat(a_start) == slot_a.astimezone(timezone.utc)


def test_reschedule_cancelled_returns_409(client, doctor, patient):
    slot = support.local_slot(11, 0, weekday=0)
    target = support.local_slot(11, 30, weekday=0)
    appt_id = _book(client, doctor.id, patient.id, slot).json()["id"]
    client.patch(f"/appointments/{appt_id}/cancel", json={"reason": "x"})
    r = client.patch(
        f"/appointments/{appt_id}/reschedule", json={"start_time": target.isoformat()}
    )
    assert r.status_code == 409


def test_patient_appointments_sorted_and_excludes_cancelled(client, doctor, patient):
    later = support.local_slot(14, 0, weekday=0)
    earlier = support.local_slot(9, 0, weekday=0)
    to_cancel = support.local_slot(10, 0, weekday=0)
    _book(client, doctor.id, patient.id, later)
    _book(client, doctor.id, patient.id, earlier)
    cid = _book(client, doctor.id, patient.id, to_cancel).json()["id"]
    client.patch(f"/appointments/{cid}/cancel", json={"reason": "x"})

    r = client.get(f"/patients/{patient.id}/appointments")
    assert r.status_code == 200
    starts = [datetime.fromisoformat(a["start_time"]) for a in r.json()]
    assert starts == sorted(starts)  # ascending
    assert len(starts) == 2  # cancelled one excluded
    assert starts[0] == earlier.astimezone(timezone.utc)
