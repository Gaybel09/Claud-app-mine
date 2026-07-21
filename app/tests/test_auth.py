import pytest
from fastapi.testclient import TestClient

from app.core import firebase


def _fake_verify(email: str, phone_number: str | None = None):
    def _verify(id_token: str) -> dict:
        if id_token != "valid-token":
            raise firebase.InvalidFirebaseTokenError("bad token")
        decoded = {"email": email, "uid": "firebase-uid"}
        if phone_number:
            decoded["phone_number"] = phone_number
        return decoded

    return _verify


def _auth_header(token: str = "valid-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_creates_user(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("new@example.com"))

    response = client.post(
        "/auth/register",
        json={"phone": "+5511999990000"},
        headers=_auth_header(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["phone"] == "+5511999990000"
    assert body["kyc_status"] == "pending"
    assert body["is_blocked"] is False


def test_register_rejects_duplicate_email(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("dup@example.com"))

    first = client.post("/auth/register", json={}, headers=_auth_header())
    assert first.status_code == 201

    second = client.post("/auth/register", json={}, headers=_auth_header())
    assert second.status_code == 409


def test_login_returns_registered_user(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("login@example.com"))

    register_response = client.post("/auth/register", json={}, headers=_auth_header())
    assert register_response.status_code == 201

    login_response = client.post("/auth/login", headers=_auth_header())
    assert login_response.status_code == 200
    assert login_response.json()["email"] == "login@example.com"


def test_login_rejects_unregistered_user(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("ghost@example.com"))

    response = client.post("/auth/login", headers=_auth_header())
    assert response.status_code == 401


def test_login_rejects_invalid_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("someone@example.com"))

    response = client.post("/auth/login", headers=_auth_header("wrong-token"))
    assert response.status_code == 401


def test_login_rejects_missing_token(client: TestClient):
    response = client.post("/auth/login")
    assert response.status_code == 401


def test_2fa_verify_matches_registered_phone(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        firebase, "verify_firebase_token", _fake_verify("2fa@example.com", phone_number="+5511988887777")
    )

    register_response = client.post(
        "/auth/register", json={"phone": "+5511988887777"}, headers=_auth_header()
    )
    assert register_response.status_code == 201

    response = client.post(
        "/auth/2fa/verify",
        json={"firebase_token": "valid-token"},
        headers=_auth_header(),
    )
    assert response.status_code == 200
    assert response.json() == {"verified": True}


def test_2fa_verify_rejects_phone_mismatch(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        firebase, "verify_firebase_token", _fake_verify("2fa-mismatch@example.com", phone_number="+5511911112222")
    )

    register_response = client.post(
        "/auth/register", json={"phone": "+5511900000000"}, headers=_auth_header()
    )
    assert register_response.status_code == 201

    response = client.post(
        "/auth/2fa/verify",
        json={"firebase_token": "valid-token"},
        headers=_auth_header(),
    )
    assert response.status_code == 401
