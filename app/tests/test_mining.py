import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ad_view import AdView, AdViewStatus
from app.models.cube import Cube, CubeType
from app.models.ledger_entry import LedgerEntry
from app.models.mining_session import MiningSession, MiningSessionStatus
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.modules.mining.service import collect_mining_session


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


def test_start_requires_confirmed_ad_view(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-unconfirmed", "unconfirmed@example.com")
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.PENDING)

    response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert response.status_code == 400

    db = SessionLocal()
    try:
        assert db.query(MiningSession).filter(MiningSession.user_id == user_id).count() == 0
    finally:
        db.close()


def test_start_uses_configured_duration_when_overridden(client: TestClient, monkeypatch):
    """MINING_SESSION_DURATION_SECONDS (default 1800 = 30min de produção)
    continua configurável mesmo sendo o valor definitivo -- ver
    app/core/config.py. Confirma que start_mining_session lê o valor atual
    do settings a cada chamada, não uma constante congelada no import do
    módulo."""
    monkeypatch.setattr(settings, "MINING_SESSION_DURATION_SECONDS", 120)
    user_id = _register_user(client, monkeypatch, "uid-short-duration", "short-duration@example.com")
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    before = datetime.now(timezone.utc)
    response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert response.status_code == 201

    started_at = datetime.fromisoformat(response.json()["started_at"].replace("Z", "+00:00"))
    ends_at = datetime.fromisoformat(response.json()["ends_at"].replace("Z", "+00:00"))
    assert started_at >= before
    assert (ends_at - started_at) == timedelta(seconds=120)


def test_start_defaults_to_thirty_minutes_when_not_overridden(client: TestClient, monkeypatch):
    assert settings.MINING_SESSION_DURATION_SECONDS == 1800
    user_id = _register_user(client, monkeypatch, "uid-default-duration", "default-duration@example.com")
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert response.status_code == 201

    started_at = datetime.fromisoformat(response.json()["started_at"].replace("Z", "+00:00"))
    ends_at = datetime.fromisoformat(response.json()["ends_at"].replace("Z", "+00:00"))
    assert (ends_at - started_at) == timedelta(minutes=30)


def test_start_rejects_second_session_on_same_cube_while_first_is_running(client: TestClient, monkeypatch):
    """Falha de segurança corrigida: sem esta checagem, um cliente que
    perdesse o estado local da tela do cubo (ex: trocar de aba e voltar)
    podia assistir um NOVO anúncio (ad_view diferente, confirmado) e
    iniciar uma segunda sessão de mineração concorrente no mesmo cubo,
    multiplicando a taxa de recompensa pretendida."""
    user_id = _register_user(client, monkeypatch, "uid-concurrent-cube", "concurrent-cube@example.com")
    cube_id = _create_cube(user_id)
    ad_view_1_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    first = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_1_id}, headers=_auth_header()
    )
    assert first.status_code == 201

    ad_view_2_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    second = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_2_id}, headers=_auth_header()
    )
    assert second.status_code == 409

    db = SessionLocal()
    try:
        running_count = (
            db.query(MiningSession)
            .filter(MiningSession.cube_id == cube_id, MiningSession.status == MiningSessionStatus.RUNNING)
            .count()
        )
        assert running_count == 1
    finally:
        db.close()


def test_start_allows_new_session_after_previous_one_is_collected(client: TestClient, monkeypatch):
    """A trava é só contra sessão RUNNING concorrente -- depois de coletada,
    o mesmo cubo pode iniciar um novo ciclo normalmente."""
    user_id = _register_user(client, monkeypatch, "uid-cycle-again", "cycle-again@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    cube_id = _create_cube(user_id)
    ad_view_1_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    first = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_1_id}, headers=_auth_header()
    )
    assert first.status_code == 201
    session_id = first.json()["id"]
    _expire_session_now(session_id)

    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "collect-cycle-again-1"},
    )
    assert collect_response.status_code == 200

    ad_view_2_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)
    second = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_2_id}, headers=_auth_header()
    )
    assert second.status_code == 201


def test_active_session_returns_null_when_none_running(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-no-active", "no-active@example.com")
    cube_id = _create_cube(user_id)

    response = client.get(
        "/mining/active-session", params={"cube_id": cube_id}, headers=_auth_header()
    )
    assert response.status_code == 200
    assert response.json() is None


def test_active_session_returns_running_session(client: TestClient, monkeypatch):
    """Prova o outro lado da correção: o app consegue descobrir a sessão
    ativa e restaurar o estado (em vez de voltar pro botão de assistir
    anúncio) -- ver mobile/lib/controllers/mining_controller.dart."""
    user_id = _register_user(client, monkeypatch, "uid-active", "active@example.com")
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert start_response.status_code == 201
    session_id = start_response.json()["id"]

    response = client.get(
        "/mining/active-session", params={"cube_id": cube_id}, headers=_auth_header()
    )
    assert response.status_code == 200
    assert response.json()["id"] == session_id
    assert response.json()["status"] == "running"


def test_active_session_does_not_leak_across_users(client: TestClient, monkeypatch):
    owner_id = _register_user(client, monkeypatch, "uid-active-owner", "active-owner@example.com")
    cube_id = _create_cube(owner_id)
    ad_view_id = _create_ad_view(owner_id, AdViewStatus.CONFIRMED)
    client.post("/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header())

    _register_user(client, monkeypatch, "uid-active-intruder", "active-intruder@example.com")
    response = client.get(
        "/mining/active-session", params={"cube_id": cube_id}, headers=_auth_header()
    )
    assert response.status_code == 200
    assert response.json() is None


def test_start_rejects_reused_ad_view(client: TestClient, monkeypatch):
    """Isolado da checagem de sessão concorrente (CubeAlreadyMiningError):
    o primeiro ciclo é coletado antes da segunda tentativa, então o único
    motivo de rejeição possível aqui é o reuso do ad_view em si."""
    user_id = _register_user(client, monkeypatch, "uid-reuse", "reuse@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    first = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert first.status_code == 201
    session_id = first.json()["id"]
    _expire_session_now(session_id)
    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "collect-reuse-1"},
    )
    assert collect_response.status_code == 200

    second = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert second.status_code == 400


def test_status_not_ready_before_ends_at(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-status", "status@example.com")
    session_id = _start_session(client, user_id)

    response = client.get("/mining/status", params={"session_id": session_id}, headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["ready_to_collect"] is False


def test_collect_before_ends_at_is_rejected(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-early", "early@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id = _start_session(client, user_id)

    response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "collect-early-1"},
    )
    assert response.status_code == 409

    db = SessionLocal()
    try:
        session = db.query(MiningSession).filter(MiningSession.id == session_id).first()
        assert session.status == MiningSessionStatus.RUNNING
    finally:
        db.close()


def test_collect_success_after_ends_at(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-collect", "collect@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id = _start_session(client, user_id)
    _expire_session_now(session_id)

    response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "collect-success-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "collected"
    reward_amount = Decimal(str(body["reward_amount"]))
    assert Decimal("0.10") <= reward_amount <= Decimal("1.00")

    status_response = client.get("/mining/status", params={"session_id": session_id}, headers=_auth_header())
    assert status_response.json()["status"] == "collected"
    assert status_response.json()["ready_to_collect"] is False

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == reward_amount


def test_collect_duplicate_idempotency_key_does_not_duplicate_reward(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-dup-collect", "dup-collect@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id = _start_session(client, user_id)
    _expire_session_now(session_id)

    headers = {**_auth_header(), "Idempotency-Key": "collect-dup-1"}
    first = client.post("/mining/collect", json={"session_id": session_id}, headers=headers)
    assert first.status_code == 200
    # Compared as Decimal, not raw JSON values: the DB's Numeric(14,2) column
    # always round-trips with two decimal places (e.g. "0.90"), while the
    # freshly-drawn in-memory amount from the first response may print with
    # fewer digits (e.g. "0.9") -- same value, different string form.
    reward_amount = Decimal(str(first.json()["reward_amount"]))

    second = client.post("/mining/collect", json={"session_id": session_id}, headers=headers)
    assert second.status_code == 200
    assert Decimal(str(second.json()["reward_amount"])) == reward_amount

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == reward_amount

    db = SessionLocal()
    try:
        entries = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.user_id == user_id, LedgerEntry.reference_id == str(session_id))
            .all()
        )
    finally:
        db.close()
    assert len(entries) == 1


def test_collect_concurrent_requests_do_not_double_collect(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-concurrent-mining", "concurrent-mining@example.com")
    _top_up_reward_fund(Decimal("100.00"))
    session_id = _start_session(client, user_id)
    _expire_session_now(session_id)

    results: list[Decimal] = []
    errors: list[Exception] = []

    def _worker():
        session = SessionLocal()
        try:
            _, reward_amount = collect_mining_session(session, user_id, session_id)
            results.append(reward_amount)
        except Exception as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 2
    assert results[0] == results[1]

    db = SessionLocal()
    try:
        entries = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.user_id == user_id, LedgerEntry.reference_id == str(session_id))
            .all()
        )
        final_balance = sum((entry.amount for entry in entries), Decimal("0"))
    finally:
        db.close()
    assert len(entries) == 1
    assert final_balance == results[0]


def test_collect_insufficient_fund_fails_safely(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-insufficient", "insufficient@example.com")
    # reward_fund is reset to balance=0 by the test fixture, so any draw
    # (minimum R$0.10) exceeds balance * safety margin.
    session_id = _start_session(client, user_id)
    _expire_session_now(session_id)

    response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "collect-insufficient-1"},
    )
    assert response.status_code == 503

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        assert fund.balance == Decimal("0.00")

        session = db.query(MiningSession).filter(MiningSession.id == session_id).first()
        assert session.status == MiningSessionStatus.RUNNING

        entries = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.user_id == user_id, LedgerEntry.reference_id == str(session_id))
            .all()
        )
        assert entries == []
    finally:
        db.close()
