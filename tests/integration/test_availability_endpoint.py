"""GET /doctors/{id}/availability."""
from __future__ import annotations

from datetime import datetime, timezone

from .. import support


def test_unknown_doctor_returns_404(client):
    r = client.get("/doctors/999/availability", params={"date": "2026-10-19"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_malformed_date_returns_422(client, doctor):
    r = client.get(f"/doctors/{doctor.id}/availability", params={"date": "not-a-date"})
    assert r.status_code == 422


def test_working_day_lists_all_slots(client, doctor):
    day = support.next_weekday_local(weekday=0).isoformat()  # a Monday
    r = client.get(f"/doctors/{doctor.id}/availability", params={"date": day})
    assert r.status_code == 200
    body = r.json()
    assert body["slot_duration_minutes"] == 30
    # Mon 09:00-13:00 + 14:00-17:00 -> 14 slots.
    assert len(body["available_slots"]) == 14


def test_non_working_day_returns_empty(client, doctor):
    saturday = support.next_weekday_local(weekday=5).isoformat()
    r = client.get(f"/doctors/{doctor.id}/availability", params={"date": saturday})
    assert r.status_code == 200
    assert r.json()["available_slots"] == []


def test_booked_slot_disappears_from_availability(client, doctor, patient):
    day = support.next_weekday_local(weekday=0).isoformat()
    slot = support.local_slot(9, 0, weekday=0)
    booked = client.post(
        "/appointments",
        json={"doctor_id": doctor.id, "patient_id": patient.id, "start_time": slot.isoformat()},
    )
    assert booked.status_code == 201
    r = client.get(f"/doctors/{doctor.id}/availability", params={"date": day})
    slots = r.json()["available_slots"]
    assert len(slots) == 13
    booked_instant = slot.astimezone(timezone.utc)
    start_instants = {datetime.fromisoformat(s["start_time"]) for s in slots}
    assert booked_instant not in start_instants
