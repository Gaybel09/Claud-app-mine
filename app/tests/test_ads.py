from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.modules.ads.service import is_ad_confirmed


def _fake_verify(uid: str, email: str):
    def _verify(id_token: str) -> dict:
        if id_token != "valid-token":
            raise firebase.InvalidFirebaseTokenError("bad token")
        return {"uid": uid, "email": email}

    return _verify


def _auth_header(token: str = "valid-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_user(client: TestClient, monkeypatch, uid: str, email: str) -> int:
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify(uid, email))
    response = client.post("/auth/register", json={}, headers=_auth_header())
    assert response.status_code == 201
    return response.json()["id"]


def _watch_ad(client: TestClient, monkeypatch, uid: str, email: str) -> tuple[int, int]:
    user_id = _register_user(client, monkeypatch, uid, email)
    response = client.post("/ads/watch", json={"ad_network": "admob"}, headers=_auth_header())
    assert response.status_code == 201
    return user_id, response.json()["id"]


def test_watch_creates_pending_ad_view(client: TestClient, monkeypatch):
    user_id, ad_view_id = _watch_ad(client, monkeypatch, "uid-watch", "watch@example.com")

    assert ad_view_id is not None

    db = SessionLocal()
    try:
        assert is_ad_confirmed(db, ad_view_id) is False
    finally:
        db.close()


def test_callback_confirms_ad_view(client: TestClient, monkeypatch):
    user_id, ad_view_id = _watch_ad(client, monkeypatch, "uid-confirm", "confirm@example.com")

    response = client.post(
        "/ads/callback",
        json={"ad_view_id": ad_view_id, "user_id": user_id, "status": "confirmed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    db = SessionLocal()
    try:
        assert is_ad_confirmed(db, ad_view_id) is True
    finally:
        db.close()


def test_callback_rejects_ad_view(client: TestClient, monkeypatch):
    user_id, ad_view_id = _watch_ad(client, monkeypatch, "uid-reject", "reject@example.com")

    response = client.post(
        "/ads/callback",
        json={"ad_view_id": ad_view_id, "user_id": user_id, "status": "rejected"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    db = SessionLocal()
    try:
        assert is_ad_confirmed(db, ad_view_id) is False
    finally:
        db.close()


def test_duplicate_callback_is_idempotent(client: TestClient, monkeypatch):
    user_id, ad_view_id = _watch_ad(client, monkeypatch, "uid-dup", "dup@example.com")

    first = client.post(
        "/ads/callback",
        json={"ad_view_id": ad_view_id, "user_id": user_id, "status": "confirmed"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "confirmed"

    # A retry from the ad network's webhook, or a conflicting late delivery --
    # either way the first outcome must stick.
    second = client.post(
        "/ads/callback",
        json={"ad_view_id": ad_view_id, "user_id": user_id, "status": "rejected"},
    )
    assert second.status_code == 200
    assert second.json()["status"] == "confirmed"


def test_callback_rejects_nonexistent_ad_view(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-ghost", "ghost@example.com")

    response = client.post(
        "/ads/callback",
        json={"ad_view_id": 999999, "user_id": user_id, "status": "confirmed"},
    )
    assert response.status_code == 404


def test_callback_rejects_ad_view_of_another_user(client: TestClient, monkeypatch):
    owner_id, ad_view_id = _watch_ad(client, monkeypatch, "uid-owner", "owner@example.com")
    other_user_id = _register_user(client, monkeypatch, "uid-intruder", "intruder@example.com")

    response = client.post(
        "/ads/callback",
        json={"ad_view_id": ad_view_id, "user_id": other_user_id, "status": "confirmed"},
    )
    assert response.status_code == 404

    db = SessionLocal()
    try:
        assert is_ad_confirmed(db, ad_view_id) is False
    finally:
        db.close()
