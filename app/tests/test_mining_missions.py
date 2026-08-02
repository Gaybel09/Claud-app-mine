from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.models.ad_view import AdView, AdViewStatus
from app.models.cube import Cube, CubeType
from app.models.ledger_entry import LedgerEntryType
from app.models.mining_session import MiningSession
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.models.user import User
from app.modules.missions.service import WEEKLY_MISSION_TARGET
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


def _start_session(client: TestClient, user_id: int) -> int:
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert response.status_code == 201
    return response.json()["id"]


def _collect(client: TestClient, session_id: int, idempotency_key: str):
    return client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": idempotency_key},
    )


def _run_one_cycle(client: TestClient, user_id: int, idempotency_key: str):
    session_id = _start_session(client, user_id)
    _expire_session_now(session_id)
    return _collect(client, session_id, idempotency_key)


def _seed_prior_reward_entries(user_id: int, count: int) -> None:
    """Pré-popula N coletas `reward` já dentro da semana corrente
    (created_at = agora), sem precisar rodar N ciclos reais de
    start/expire/collect pela API -- só o ciclo que o teste quer observar
    de verdade roda pela API."""
    db = SessionLocal()
    try:
        for i in range(count):
            create_ledger_entry(
                db, user_id=user_id, type=LedgerEntryType.REWARD, amount=Decimal("0.30"), reference_id=f"seed-{i}"
            )
        db.commit()
    finally:
        db.close()


def _get_user(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def test_10th_weekly_collection_completes_mission_but_pays_normal_amount(client: TestClient, monkeypatch):
    """A 10ª coleta fecha a missão (X/10 -> completa), mas ela mesma NÃO
    ganha o multiplicador -- só as coletas seguintes, dentro da janela de
    24h (decisão confirmada)."""
    user_id = _register_user(client, monkeypatch, "uid-mission-1", "mission-1@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    _seed_prior_reward_entries(user_id, WEEKLY_MISSION_TARGET - 1)

    response = _run_one_cycle(client, user_id, "mission-1-tenth")
    assert response.status_code == 200
    assert Decimal(str(response.json()["reward_amount"])) == Decimal("0.30")

    status = client.get("/missions/weekly", headers=_auth_header())
    body = status.json()
    assert body["progress"] == WEEKLY_MISSION_TARGET
    assert body["completed"] is True
    assert body["multiplier_active"] is True
    assert body["multiplier_expires_at"] is not None


def test_11th_collection_within_24h_gets_1_5x_multiplier(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-mission-2", "mission-2@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    _seed_prior_reward_entries(user_id, WEEKLY_MISSION_TARGET - 1)

    tenth = _run_one_cycle(client, user_id, "mission-2-tenth")
    assert Decimal(str(tenth.json()["reward_amount"])) == Decimal("0.30")

    eleventh = _run_one_cycle(client, user_id, "mission-2-eleventh")
    assert eleventh.status_code == 200
    # 0.30 * 1.5 = 0.45, sem cubo épico envolvido.
    assert Decimal(str(eleventh.json()["reward_amount"])) == Decimal("0.45")


def test_multiplier_stacks_multiplicatively_with_epic_bonus(client: TestClient, monkeypatch):
    """Decisão confirmada: os dois bônus se acumulam multiplicando em
    cadeia (0.30 * 1.25 * 1.5 = 0.5625, truncado ROUND_DOWN -> 0.56), não
    somando as porcentagens (o que daria 0.30 * 1.75 = 0.525 -> 0.52)."""
    user_id = _register_user(client, monkeypatch, "uid-mission-3", "mission-3@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    _seed_prior_reward_entries(user_id, WEEKLY_MISSION_TARGET)
    # Ativa o multiplicador manualmente (equivalente a já ter completado a
    # missão momentos atrás) -- o que este teste quer observar é só o
    # empilhamento com o Cubo Épico, não a ativação em si (já coberta
    # acima).
    from app.modules.missions.service import WEEKLY_MISSION_MULTIPLIER_DURATION

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        user.weekly_mission_multiplier_until = datetime.now(timezone.utc) + WEEKLY_MISSION_MULTIPLIER_DURATION
        db.commit()
    finally:
        db.close()

    cube_id = _create_cube(user_id)
    start_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    start = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": start_ad_view_id}, headers=_auth_header()
    )
    assert start.status_code == 201
    session_id = start.json()["id"]

    for _ in range(2):
        video_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
        video = client.post(
            "/mining/epic-bonus",
            json={"session_id": session_id, "ad_view_id": video_ad_view_id},
            headers=_auth_header(),
        )
        assert video.status_code == 200
    assert video.json()["epic_bonus_applied"] is True

    _expire_session_now(session_id)
    collect_response = _collect(client, session_id, "mission-3-collect")
    assert collect_response.status_code == 200
    assert Decimal(str(collect_response.json()["reward_amount"])) == Decimal("0.56")


def test_multiplier_does_not_apply_once_expired(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-mission-4", "mission-4@example.com")
    _top_up_reward_fund(Decimal("100.00"))

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        user.weekly_mission_multiplier_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    response = _run_one_cycle(client, user_id, "mission-4-collect")
    assert response.status_code == 200
    assert Decimal(str(response.json()["reward_amount"])) == Decimal("0.30")


def test_speedup_has_no_effect_on_reward_or_mission_progress(client: TestClient, monkeypatch):
    """Acelerar só mexe em ends_at -- não deve interferir em nada do
    cálculo de recompensa nem da missão semanal."""
    user_id = _register_user(client, monkeypatch, "uid-mission-5", "mission-5@example.com")
    _top_up_reward_fund(Decimal("100.00"))

    cube_id = _create_cube(user_id)
    start_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    start = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": start_ad_view_id}, headers=_auth_header()
    )
    session_id = start.json()["id"]

    speedup_ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    speedup = client.post(
        "/mining/speedup",
        json={"session_id": session_id, "ad_view_id": speedup_ad_view_id},
        headers=_auth_header(),
    )
    assert speedup.status_code == 200

    _expire_session_now(session_id)
    collect_response = _collect(client, session_id, "mission-5-collect")
    assert collect_response.status_code == 200
    assert Decimal(str(collect_response.json()["reward_amount"])) == Decimal("0.30")

    status = client.get("/missions/weekly", headers=_auth_header())
    assert status.json()["progress"] == 1
