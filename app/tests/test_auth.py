from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.models.user import User


def _fake_verify(uid: str, email: str, phone_number: str | None = None):
    def _verify(id_token: str) -> dict:
        if id_token != "valid-token":
            raise firebase.InvalidFirebaseTokenError("bad token")
        decoded = {"uid": uid, "email": email}
        if phone_number:
            decoded["phone_number"] = phone_number
        return decoded

    return _verify


def _auth_header(token: str = "valid-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_creates_user(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-new", "new@example.com"))

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


def test_register_saves_device_id_from_header(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-device", "device@example.com"))

    response = client.post(
        "/auth/register",
        json={},
        headers={**_auth_header(), "X-Device-Id": "device-abc-123"},
    )
    assert response.status_code == 201
    user_id = response.json()["id"]

    # device_id não é exposto no UserRead público -- confirma direto no banco.
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        assert user.device_id == "device-abc-123"
    finally:
        db.close()


def test_register_without_device_id_header_saves_null(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-no-device", "no-device@example.com"))

    response = client.post("/auth/register", json={}, headers=_auth_header())
    assert response.status_code == 201
    user_id = response.json()["id"]

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        assert user.device_id is None
    finally:
        db.close()


def test_register_rejects_duplicate_firebase_uid(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-dup", "dup@example.com"))

    first = client.post("/auth/register", json={}, headers=_auth_header())
    assert first.status_code == 201

    second = client.post("/auth/register", json={}, headers=_auth_header())
    assert second.status_code == 409


def test_register_rejects_duplicate_firebase_uid_even_with_different_email(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-dup-2", "first@example.com"))
    first = client.post("/auth/register", json={}, headers=_auth_header())
    assert first.status_code == 201

    # Same firebase_uid, different email: still the same account, so this
    # must be rejected as a duplicate registration, not treated as a new user.
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-dup-2", "second@example.com"))
    second = client.post("/auth/register", json={}, headers=_auth_header())
    assert second.status_code == 409


def test_login_returns_registered_user(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-login", "login@example.com"))

    register_response = client.post("/auth/register", json={}, headers=_auth_header())
    assert register_response.status_code == 201

    login_response = client.post("/auth/login", headers=_auth_header())
    assert login_response.status_code == 200
    assert login_response.json()["email"] == "login@example.com"


def test_login_recognizes_user_after_email_change_in_firebase(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-email-change", "old@example.com"))

    register_response = client.post("/auth/register", json={}, headers=_auth_header())
    assert register_response.status_code == 201
    user_id = register_response.json()["id"]

    # The user changes their e-mail in Firebase: the token now carries a new
    # email but the same firebase_uid. Login must still resolve to the same
    # account (joined by firebase_uid, not email).
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-email-change", "new@example.com"))

    login_response = client.post("/auth/login", headers=_auth_header())
    assert login_response.status_code == 200
    body = login_response.json()
    assert body["id"] == user_id
    # email is informative only; it reflects what was stored at
    # registration and is not kept in sync automatically by login.
    assert body["email"] == "old@example.com"


def test_login_rejects_unregistered_user(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-ghost", "ghost@example.com"))

    response = client.post("/auth/login", headers=_auth_header())
    assert response.status_code == 401


def test_login_rejects_invalid_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-someone", "someone@example.com"))

    response = client.post("/auth/login", headers=_auth_header("wrong-token"))
    assert response.status_code == 401


def test_login_rejects_missing_token(client: TestClient):
    response = client.post("/auth/login")
    assert response.status_code == 401


def test_2fa_verify_matches_registered_phone(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        firebase,
        "verify_firebase_token",
        _fake_verify("uid-2fa", "2fa@example.com", phone_number="+5511988887777"),
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
        firebase,
        "verify_firebase_token",
        _fake_verify("uid-2fa-mismatch", "2fa-mismatch@example.com", phone_number="+5511911112222"),
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
