from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.models.ledger_entry import LedgerEntryType
from app.models.user import User
from app.modules.levels.service import (
    LEVEL_XP_BASE,
    LEVEL_XP_STEP,
    WEEKLY_MISSION_XP_BONUS,
    XP_PER_REAL,
    cumulative_xp_for_level,
    get_level_status,
    level_from_xp,
    total_xp,
    xp_from_reward_total,
    xp_to_next_level,
)
from app.modules.wallet.service import create_ledger_entry


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


def _create_user(uid: str, email: str) -> int:
    db = SessionLocal()
    try:
        user = User(firebase_uid=uid, email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _get_user(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def _credit_reward(user_id: int, amount: Decimal, reference_id: str) -> None:
    db = SessionLocal()
    try:
        create_ledger_entry(db, user_id=user_id, type=LedgerEntryType.REWARD, amount=amount, reference_id=reference_id)
        db.commit()
    finally:
        db.close()


def _set_weekly_missions_completed(user_id: int, count: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        user.weekly_missions_completed = count
        db.commit()
    finally:
        db.close()


# --- curva de nível -------------------------------------------------------


def test_level_1_requires_zero_xp():
    assert cumulative_xp_for_level(1) == 0


def test_xp_to_next_level_grows_linearly():
    assert xp_to_next_level(1) == LEVEL_XP_BASE
    assert xp_to_next_level(2) == LEVEL_XP_BASE + LEVEL_XP_STEP
    assert xp_to_next_level(3) == LEVEL_XP_BASE + 2 * LEVEL_XP_STEP


def test_cumulative_xp_matches_sum_of_individual_level_costs():
    # A fórmula fechada de cumulative_xp_for_level precisa bater com a soma
    # ingênua de xp_to_next_level(1..level-1), pra qualquer nível.
    running_total = 0
    for level in range(1, 30):
        assert cumulative_xp_for_level(level) == running_total
        running_total += xp_to_next_level(level)


def test_level_from_xp_boundaries_around_a_level_up():
    boundary = cumulative_xp_for_level(3)
    just_below = level_from_xp(boundary - 1)
    at_boundary = level_from_xp(boundary)

    assert just_below.level == 2
    assert just_below.xp_into_level == xp_to_next_level(2) - 1

    assert at_boundary.level == 3
    assert at_boundary.xp_into_level == 0
    assert at_boundary.xp_for_next_level == xp_to_next_level(3)


def test_level_from_zero_xp_is_level_1():
    status = level_from_xp(0)
    assert status.level == 1
    assert status.xp_into_level == 0
    assert status.xp_for_next_level == LEVEL_XP_BASE


# --- xp derivado do dinheiro ganho + bônus de missão ----------------------


def test_xp_from_reward_total_is_exactly_100x_the_reais_amount():
    assert xp_from_reward_total(Decimal("0.30")) == 30
    assert xp_from_reward_total(Decimal("0.01")) == 1
    assert xp_from_reward_total(Decimal("12.34")) == 1234
    assert xp_from_reward_total(Decimal("0.00")) == 0


def test_total_xp_adds_mining_xp_and_mission_bonus_xp():
    # R$3,00 histórico (300 XP) + 2 missões completadas (2 * 100 = 200 XP).
    assert total_xp(Decimal("3.00"), 2) == 300 + 2 * WEEKLY_MISSION_XP_BONUS


def test_get_level_status_reflects_lifetime_reward_and_missions_completed():
    user_id = _create_user("uid-level-1", "level-1@example.com")
    _credit_reward(user_id, Decimal("1.00"), "session-1")
    _credit_reward(user_id, Decimal("0.50"), "session-2")
    _set_weekly_missions_completed(user_id, 1)

    db = SessionLocal()
    try:
        status = get_level_status(db, _get_user(user_id))
    finally:
        db.close()

    expected_xp = xp_from_reward_total(Decimal("1.50")) + WEEKLY_MISSION_XP_BONUS
    assert status.xp == expected_xp
    assert status == level_from_xp(expected_xp)


def test_get_level_status_for_brand_new_user_is_level_1_zero_xp():
    user_id = _create_user("uid-level-2", "level-2@example.com")
    db = SessionLocal()
    try:
        status = get_level_status(db, _get_user(user_id))
    finally:
        db.close()
    assert status.level == 1
    assert status.xp == 0


# --- GET /levels/me --------------------------------------------------------


def test_levels_me_endpoint_for_new_user(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-levels-endpoint-1", "levels-endpoint-1@example.com")
    response = client.get("/levels/me", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["level"] == 1
    assert body["xp"] == 0
    assert body["xp_for_next_level"] == LEVEL_XP_BASE


def test_levels_me_endpoint_requires_auth(client: TestClient):
    response = client.get("/levels/me")
    assert response.status_code in (401, 403)


def test_levels_me_reflects_reward_earned_via_the_real_mining_flow(client: TestClient, monkeypatch):
    """Ponta a ponta: uma coleta de verdade via /mining/collect deve
    refletir no XP devolvido por /levels/me, sem precisar de nenhum passo
    manual -- o XP é derivado do mesmo ledger que a coleta já grava."""
    from datetime import datetime, timedelta, timezone

    from app.models.ad_view import AdView, AdViewStatus
    from app.models.cube import Cube, CubeType
    from app.models.mining_session import MiningSession
    from app.models.reward_fund import SINGLETON_ID, RewardFund

    def _top_up_reward_fund(amount: Decimal) -> None:
        db = SessionLocal()
        try:
            fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
            fund.balance += amount
            fund.total_in += amount
            db.commit()
        finally:
            db.close()

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

    def _expire_session_now(session_id: int) -> None:
        db = SessionLocal()
        try:
            session = db.query(MiningSession).filter(MiningSession.id == session_id).first()
            session.ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()

    user_id = _register_user(client, monkeypatch, "uid-levels-e2e", "levels-e2e@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    start = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    session_id = start.json()["id"]
    _expire_session_now(session_id)
    collect = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "levels-e2e-collect"},
    )
    assert collect.status_code == 200
    reward_amount = Decimal(str(collect.json()["reward_amount"]))

    level_response = client.get("/levels/me", headers=_auth_header())
    assert level_response.status_code == 200
    assert level_response.json()["xp"] == xp_from_reward_total(reward_amount)
