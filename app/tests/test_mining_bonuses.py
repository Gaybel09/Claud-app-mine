from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ad_view import AdView, AdViewStatus
from app.models.cube import Cube, CubeType
from app.models.mining_session import MiningSession, MiningSessionStatus
from app.models.reward_fund import SINGLETON_ID, RewardFund


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


def _create_cube(user_id: int) -> int:
    db = SessionLocal()
    try:
        cube = Cube(user_id=user_id, type=CubeType.COMUM, speed=Decimal("1.00"), bonus_chance=Decimal("0.05"))
        db.add(cube)
        db.commit()
        db.refresh(cube)
        return cube.id
    finally:
        db.close()


def _create_ad_view(user_id: int, status: str) -> int:
    db = SessionLocal()
    try:
        ad_view = AdView(user_id=user_id, ad_network="admob", status=status)
        db.add(ad_view)
        db.commit()
        db.refresh(ad_view)
        return ad_view.id
    finally:
        db.close()


def _top_up_reward_fund(amount: Decimal) -> None:
    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        fund.balance += amount
        fund.total_in += amount
        db.commit()
    finally:
        db.close()


def _expire_session_now(session_id: int) -> None:
    db = SessionLocal()
    try:
        session = db.query(MiningSession).filter(MiningSession.id == session_id).first()
        session.ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()


def _start_session(client: TestClient, user_id: int) -> tuple[int, int]:
    """Devolve (session_id, start_ad_view_id) -- o ad_view usado pra
    iniciar, distinto do que qualquer bônus vai usar depois."""
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert response.status_code == 201
    return response.json()["id"], ad_view_id


# --- POST /mining/epic-bonus ---------------------------------------------


def test_epic_bonus_applies_1_25x_multiplier_on_collect(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-epic-1", "epic-1@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id, _ = _start_session(client, user_id)
    bonus_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    response = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": bonus_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 200
    assert response.json()["epic_bonus_applied"] is True

    _expire_session_now(session_id)
    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "epic-collect-1"},
    )
    assert collect_response.status_code == 200
    # reward_config.value_per_session default é 0.30 (fixture _clean_tables)
    # -- 0.30 * 1.25 = 0.375, truncado (ROUND_DOWN) pra 0.37.
    assert Decimal(str(collect_response.json()["reward_amount"])) == Decimal("0.37")


def test_epic_bonus_not_applied_pays_normal_amount(client: TestClient, monkeypatch):
    """Controle: sem usar o bônus, a mesma reward_config paga o valor cheio
    (0.30), não 0.37 -- prova que o multiplicador só entra quando usado."""
    user_id = _register_user(client, monkeypatch, "uid-epic-control", "epic-control@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id, _ = _start_session(client, user_id)
    _expire_session_now(session_id)

    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "epic-control-collect-1"},
    )
    assert collect_response.status_code == 200
    assert Decimal(str(collect_response.json()["reward_amount"])) == Decimal("0.30")


def test_epic_bonus_rejects_second_use_on_same_session(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-epic-2", "epic-2@example.com")
    session_id, _ = _start_session(client, user_id)
    first_bonus_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    second_bonus_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    first = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": first_bonus_ad_view_id},
        headers=_auth_header(),
    )
    assert first.status_code == 200

    second = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": second_bonus_ad_view_id},
        headers=_auth_header(),
    )
    assert second.status_code == 409


def test_epic_bonus_rejects_reusing_the_ad_view_that_started_the_session(client: TestClient, monkeypatch):
    """Sem essa checagem, um único anúncio (o que já liberou /mining/start)
    poderia "pagar" o bônus de novo de graça, sem assistir nada a mais."""
    user_id = _register_user(client, monkeypatch, "uid-epic-3", "epic-3@example.com")
    session_id, start_ad_view_id = _start_session(client, user_id)

    response = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": start_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 400


def test_epic_bonus_requires_confirmed_ad_view(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-epic-4", "epic-4@example.com")
    session_id, _ = _start_session(client, user_id)
    pending_ad_view_id = _create_ad_view(user_id, AdViewStatus.PENDING)

    response = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": pending_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 400


def test_epic_bonus_rejects_ad_view_belonging_to_another_user(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-epic-5", "epic-5@example.com")
    session_id, _ = _start_session(client, user_id)

    other_user_id = _register_user(client, monkeypatch, "uid-epic-5-other", "epic-5-other@example.com")
    other_ad_view_id = _create_ad_view(other_user_id, AdViewStatus.CONFIRMED)

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-epic-5", "epic-5@example.com"))
    response = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": other_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 400


def test_epic_bonus_rejects_already_collected_session(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-epic-6", "epic-6@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id, _ = _start_session(client, user_id)
    _expire_session_now(session_id)
    client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "epic-6-collect"},
    )

    bonus_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    response = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": bonus_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 409


def test_epic_bonus_returns_404_for_nonexistent_session(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-epic-7", "epic-7@example.com")
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    response = client.post(
        "/mining/epic-bonus",
        json={"session_id": 999999, "ad_view_id": ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 404


def test_epic_bonus_does_not_leak_across_users(client: TestClient, monkeypatch):
    owner_id = _register_user(client, monkeypatch, "uid-epic-8-owner", "epic-8-owner@example.com")
    session_id, _ = _start_session(client, owner_id)

    attacker_id = _register_user(client, monkeypatch, "uid-epic-8-attacker", "epic-8-attacker@example.com")
    attacker_ad_view_id = _create_ad_view(attacker_id, AdViewStatus.CONFIRMED)

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-epic-8-attacker", "epic-8-attacker@example.com"))
    response = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": attacker_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 404


# --- POST /mining/speedup -------------------------------------------------


def test_speedup_halves_the_remaining_time(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "MINING_SESSION_DURATION_SECONDS", 1200)  # 20min
    user_id = _register_user(client, monkeypatch, "uid-speedup-1", "speedup-1@example.com")
    session_id, _ = _start_session(client, user_id)

    status_before = client.get("/mining/status", params={"session_id": session_id}, headers=_auth_header())
    original_ends_at = datetime.fromisoformat(status_before.json()["ends_at"].replace("Z", "+00:00"))

    speedup_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    before = datetime.now(timezone.utc)
    response = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": speedup_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 200
    assert response.json()["speedup_used"] is True

    new_ends_at = datetime.fromisoformat(response.json()["ends_at"].replace("Z", "+00:00"))
    expected_remaining = (original_ends_at - before) / 2
    actual_remaining = new_ends_at - before
    assert abs((actual_remaining - expected_remaining).total_seconds()) < 2
    assert new_ends_at < original_ends_at


def test_speedup_rejects_second_use_on_same_session(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "MINING_SESSION_DURATION_SECONDS", 1200)
    user_id = _register_user(client, monkeypatch, "uid-speedup-2", "speedup-2@example.com")
    session_id, _ = _start_session(client, user_id)

    first_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    second_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    first = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": first_ad_view_id},
        headers=_auth_header(),
    )
    assert first.status_code == 200

    second = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": second_ad_view_id},
        headers=_auth_header(),
    )
    assert second.status_code == 409


def test_speedup_does_not_accumulate_via_reused_ad_view(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-speedup-3", "speedup-3@example.com")
    session_id, start_ad_view_id = _start_session(client, user_id)

    response = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": start_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 400


def test_speedup_rejects_when_session_already_ready_to_collect(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-speedup-4", "speedup-4@example.com")
    session_id, _ = _start_session(client, user_id)
    _expire_session_now(session_id)

    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    response = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 409


def test_speedup_rejects_on_already_collected_session(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-speedup-5", "speedup-5@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id, _ = _start_session(client, user_id)
    _expire_session_now(session_id)
    client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "speedup-5-collect"},
    )

    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    response = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 409


def test_speedup_requires_confirmed_ad_view(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-speedup-6", "speedup-6@example.com")
    session_id, _ = _start_session(client, user_id)
    pending_ad_view_id = _create_ad_view(user_id, AdViewStatus.PENDING)

    response = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": pending_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 400


def test_speedup_returns_404_for_nonexistent_session(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-speedup-7", "speedup-7@example.com")
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    response = client.post(
        "/mining/speedup",
        json={"session_id": 999999, "ad_view_id": ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 404


def test_speedup_does_not_leak_across_users(client: TestClient, monkeypatch):
    owner_id = _register_user(client, monkeypatch, "uid-speedup-8-owner", "speedup-8-owner@example.com")
    session_id, _ = _start_session(client, owner_id)

    attacker_id = _register_user(client, monkeypatch, "uid-speedup-8-attacker", "speedup-8-attacker@example.com")
    attacker_ad_view_id = _create_ad_view(attacker_id, AdViewStatus.CONFIRMED)

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-speedup-8-attacker", "speedup-8-attacker@example.com"))
    response = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": attacker_ad_view_id},
        headers=_auth_header(),
    )
    assert response.status_code == 404


# --- interação entre os dois bônus -----------------------------------------


def test_both_bonuses_can_be_used_in_the_same_session(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "MINING_SESSION_DURATION_SECONDS", 1200)
    user_id = _register_user(client, monkeypatch, "uid-both-1", "both-1@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id, _ = _start_session(client, user_id)

    epic_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    epic_response = client.post(
        "/mining/epic-bonus",
        json={"session_id": session_id, "ad_view_id": epic_ad_view_id},
        headers=_auth_header(),
    )
    assert epic_response.status_code == 200

    speedup_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    speedup_response = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": speedup_ad_view_id},
        headers=_auth_header(),
    )
    assert speedup_response.status_code == 200
    assert speedup_response.json()["epic_bonus_applied"] is True
    assert speedup_response.json()["speedup_used"] is True

    _expire_session_now(session_id)
    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "both-1-collect"},
    )
    assert collect_response.status_code == 200
    assert Decimal(str(collect_response.json()["reward_amount"])) == Decimal("0.37")
