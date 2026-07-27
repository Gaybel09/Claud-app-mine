from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import firebase
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ad_view import AdView, AdViewStatus
from app.models.cube import Cube, CubeType
from app.models.mining_session import MiningSession, MiningSessionStatus
from app.modules.mining.service import MINING_SESSION_DURATION

ADMIN_HEADER = "X-Admin-Token"


def _fake_verify(uid: str, email: str):
    def _verify(id_token: str) -> dict:
        if id_token != "valid-token":
            raise firebase.InvalidFirebaseTokenError("bad token")
        return {"uid": uid, "email": email}

    return _verify


def _auth_header(token: str = "valid-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def _start_session(client: TestClient, monkeypatch, uid: str, email: str) -> int:
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify(uid, email))
    register = client.post("/auth/register", json={}, headers=_auth_header())
    assert register.status_code == 201
    user_id = register.json()["id"]

    db = SessionLocal()
    try:
        cube = Cube(user_id=user_id, type=CubeType.COMUM, speed=Decimal("1.00"), bonus_chance=Decimal("0.05"))
        db.add(cube)
        db.commit()
        db.refresh(cube)
        cube_id = cube.id

        ad_view = AdView(user_id=user_id, ad_network="admob", status=AdViewStatus.CONFIRMED)
        db.add(ad_view)
        db.commit()
        db.refresh(ad_view)
        ad_view_id = ad_view.id
    finally:
        db.close()

    start = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert start.status_code == 201
    return start.json()["id"]


@pytest.fixture(autouse=True)
def _enable_diagnostic_endpoints(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_DIAGNOSTIC_ENDPOINTS", True)


def test_force_ready_returns_404_when_diagnostics_disabled_even_with_valid_token(
    client: TestClient, monkeypatch
):
    monkeypatch.setattr(settings, "ENABLE_DIAGNOSTIC_ENDPOINTS", False)
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get(
        "/admin/mining/force-ready",
        params={"session_id": 1},
        headers={ADMIN_HEADER: "the-real-token"},
    )
    assert response.status_code == 404


def test_force_ready_returns_404_when_token_not_configured(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", None)

    response = client.get(
        "/admin/mining/force-ready", params={"session_id": 1}, headers={ADMIN_HEADER: "anything"}
    )
    assert response.status_code == 404


def test_force_ready_rejects_wrong_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get(
        "/admin/mining/force-ready", params={"session_id": 1}, headers={ADMIN_HEADER: "wrong-token"}
    )
    assert response.status_code == 403


def test_force_ready_returns_404_for_nonexistent_session(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get(
        "/admin/mining/force-ready",
        params={"session_id": 999999},
        headers={ADMIN_HEADER: "the-real-token"},
    )
    assert response.status_code == 404


def test_force_ready_makes_a_running_session_immediately_collectible(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    session_id = _start_session(client, monkeypatch, "uid-force-ready", "force-ready@example.com")

    status_before = client.get(
        "/mining/status", params={"session_id": session_id}, headers=_auth_header()
    )
    assert status_before.json()["ready_to_collect"] is False

    response = client.get(
        "/admin/mining/force-ready",
        params={"session_id": session_id},
        headers={ADMIN_HEADER: "the-real-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == session_id
    assert body["status"] == "running"

    status_after = client.get(
        "/mining/status", params={"session_id": session_id}, headers=_auth_header()
    )
    assert status_after.json()["ready_to_collect"] is True


def test_force_ready_does_not_touch_the_production_duration_constant(client: TestClient, monkeypatch):
    """A garantia central desta abordagem (em vez de uma env var global):
    MINING_SESSION_DURATION -- usada por toda sessão nova, inclusive de
    outros usuários em paralelo -- nunca é alterada por este endpoint."""
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    original_duration = MINING_SESSION_DURATION
    session_id = _start_session(client, monkeypatch, "uid-force-ready-2", "force-ready-2@example.com")

    client.get(
        "/admin/mining/force-ready",
        params={"session_id": session_id},
        headers={ADMIN_HEADER: "the-real-token"},
    )

    from app.modules.mining import service as mining_service

    assert mining_service.MINING_SESSION_DURATION == original_duration

    db = SessionLocal()
    try:
        session = db.query(MiningSession).filter(MiningSession.id == session_id).first()
        assert session.ends_at < datetime.now(timezone.utc)
        assert session.status == MiningSessionStatus.RUNNING
    finally:
        db.close()
