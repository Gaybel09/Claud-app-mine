from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.models.cube import Cube, CubeType


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


def test_register_creates_exactly_one_starter_cube(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-starter-cube", "starter@example.com")

    db = SessionLocal()
    try:
        cubes = db.query(Cube).filter(Cube.user_id == user_id).all()
    finally:
        db.close()

    assert len(cubes) == 1
    cube = cubes[0]
    assert cube.type == CubeType.COMUM
    assert cube.speed == Decimal("1.00")
    assert cube.bonus_chance == Decimal("0.0500")


def test_cubes_me_returns_only_authenticated_users_cubes(client: TestClient, monkeypatch):
    user_a_id = _register_user(client, monkeypatch, "uid-cubes-a", "cubes-a@example.com")
    user_b_id = _register_user(client, monkeypatch, "uid-cubes-b", "cubes-b@example.com")
    assert user_a_id != user_b_id

    # Re-arm the fake verifier as user A before calling GET /cubes/me, since
    # the bearer token itself is just the literal string "valid-token" --
    # identity comes entirely from whatever verify_firebase_token returns.
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-cubes-a", "cubes-a@example.com"))
    response = client.get("/cubes/me", headers=_auth_header())

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["user_id"] == user_a_id
    assert body[0]["type"] == "comum"


def test_cubes_me_requires_authentication(client: TestClient):
    response = client.get("/cubes/me")
    assert response.status_code == 401
