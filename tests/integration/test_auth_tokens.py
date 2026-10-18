"""/auth/me plus refresh-token issue, rotation, reuse detection, and logout."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _login(anon_client, email="p@example.com", password="patientpass123"):
    r = anon_client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200
    return r.json()


def _auth(token: str) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_me_returns_current_user(patient_client, patient):
    r = patient_client.get("/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "p@example.com"
    assert body["role"] == "patient"
    assert body["patient_id"] == patient.id


def test_me_requires_auth(anon_client):
    assert anon_client.get("/auth/me").status_code == 401


def test_login_returns_access_and_refresh(anon_client, patient_user):
    body = _login(anon_client)
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_refresh_issues_working_access_and_rotates(anon_client, patient_user):
    first = _login(anon_client)
    r = anon_client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    rotated = r.json()
    # The refresh token is always rotated to a new random value.
    assert rotated["refresh_token"] != first["refresh_token"]
    # The returned access token works. (It may be byte-identical to the original
    # when issued in the same second — JWTs carry second-resolution iat/exp — so
    # we assert it is valid, not that it differs.)
    assert _auth(rotated["access_token"]).get("/auth/me").status_code == 200


def test_old_refresh_token_rejected_after_rotation(anon_client, patient_user):
    first = _login(anon_client)
    anon_client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    # Reusing the now-rotated token is rejected.
    reuse = anon_client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401


def test_logout_revokes_refresh_token(anon_client, patient_user):
    body = _login(anon_client)
    assert anon_client.post("/auth/logout", json={"refresh_token": body["refresh_token"]}).status_code == 204
    after = anon_client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert after.status_code == 401


def test_refresh_with_garbage_token_401(anon_client):
    r = anon_client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401
