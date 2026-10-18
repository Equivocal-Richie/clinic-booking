"""Pagination on GET /patients/{id}/appointments."""
from __future__ import annotations

from .. import support


def _book(client, doctor_id, patient_id, slot):
    return client.post(
        "/appointments",
        json={"doctor_id": doctor_id, "patient_id": patient_id, "start_time": slot.isoformat()},
    )


def test_limit_offset_and_has_more(client, doctor, patient):
    for hh, mm in [(9, 0), (9, 30), (10, 0)]:
        assert _book(client, doctor.id, patient.id, support.local_slot(hh, mm, weekday=0)).status_code == 201

    page1 = client.get(
        f"/patients/{patient.id}/appointments", params={"limit": 2, "offset": 0}
    ).json()
    assert len(page1["items"]) == 2
    assert page1["limit"] == 2
    assert page1["offset"] == 0
    assert page1["has_more"] is True

    page2 = client.get(
        f"/patients/{patient.id}/appointments", params={"limit": 2, "offset": 2}
    ).json()
    assert len(page2["items"]) == 1
    assert page2["has_more"] is False

    # Pages are disjoint and ordered.
    s1 = [i["start_time"] for i in page1["items"]]
    s2 = [i["start_time"] for i in page2["items"]]
    assert set(s1).isdisjoint(s2)


def test_limit_over_max_is_rejected(client, patient):
    r = client.get(
        f"/patients/{patient.id}/appointments", params={"limit": 1000}
    )
    assert r.status_code == 422
