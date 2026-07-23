"""Testes de integração do fluxo completo do MVP (Fase 1, prompt 8):

cadastro -> login -> assistir anúncio -> callback confirma -> iniciar
mineração -> aguardar (mock do relógio) -> coletar recompensa -> saldo
atualizado no wallet -- exercitando os endpoints HTTP reais de ponta a
ponta, não as funções de serviço isoladas (essas já têm cobertura própria
em test_auth.py/test_ads.py/test_mining.py/test_wallet.py).

"Mock do relógio": em vez de esperar 2h de verdade ou mockar
datetime.now(), empurramos mining_sessions.ends_at pro passado
diretamente no banco -- do ponto de vista do código (que sempre calcula
now() >= ends_at), é indistinguível de esperar o tempo real passar.
"""

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
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


def _register_and_login(client: TestClient, monkeypatch, uid: str, email: str) -> int:
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify(uid, email))

    register_response = client.post("/auth/register", json={}, headers=_auth_header())
    assert register_response.status_code == 201
    user_id = register_response.json()["id"]

    login_response = client.post("/auth/login", headers=_auth_header())
    assert login_response.status_code == 200
    assert login_response.json()["id"] == user_id

    return user_id


def _get_starter_cube_id(client: TestClient) -> int:
    response = client.get("/cubes/me", headers=_auth_header())
    assert response.status_code == 200
    cubes = response.json()
    assert len(cubes) == 1, "registro deveria ter dado exatamente um cubo comum"
    return cubes[0]["id"]


def _watch_ad(client: TestClient) -> int:
    response = client.post("/ads/watch", json={"ad_network": "admob"}, headers=_auth_header())
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    return response.json()["id"]


def _confirm_ad(client: TestClient, ad_view_id: int, user_id: int) -> None:
    response = client.post(
        "/ads/callback",
        json={"ad_view_id": ad_view_id, "user_id": user_id, "status": "confirmed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


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


def test_full_mvp_flow_register_to_wallet_balance(client: TestClient, monkeypatch):
    user_id = _register_and_login(client, monkeypatch, "uid-mvp-flow", "mvp-flow@example.com")
    cube_id = _get_starter_cube_id(client)
    _top_up_reward_fund(Decimal("100.00"))

    ad_view_id = _watch_ad(client)
    _confirm_ad(client, ad_view_id, user_id)

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert start_response.status_code == 201
    session_id = start_response.json()["id"]
    assert start_response.json()["status"] == "running"

    status_before = client.get("/mining/status", params={"session_id": session_id}, headers=_auth_header())
    assert status_before.status_code == 200
    assert status_before.json()["ready_to_collect"] is False

    # Aguardar o ciclo de 2h -- mock do relógio via ends_at, não sleep real.
    _expire_session_now(session_id)

    status_after = client.get("/mining/status", params={"session_id": session_id}, headers=_auth_header())
    assert status_after.status_code == 200
    assert status_after.json()["ready_to_collect"] is True

    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "mvp-flow-collect-1"},
    )
    assert collect_response.status_code == 200
    assert collect_response.json()["status"] == "collected"
    reward_amount = Decimal(str(collect_response.json()["reward_amount"]))
    assert Decimal("0.10") <= reward_amount <= Decimal("1.00")

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert balance_response.status_code == 200
    assert Decimal(str(balance_response.json()["balance"])) == reward_amount

    statement_response = client.get("/wallet/statement", headers=_auth_header())
    assert statement_response.status_code == 200
    items = statement_response.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "reward"
    assert Decimal(str(items[0]["amount"])) == reward_amount
    assert items[0]["reference_id"] == str(session_id)


def test_collect_before_ends_at_is_rejected(client: TestClient, monkeypatch):
    user_id = _register_and_login(client, monkeypatch, "uid-mvp-early", "mvp-early@example.com")
    cube_id = _get_starter_cube_id(client)
    _top_up_reward_fund(Decimal("100.00"))

    ad_view_id = _watch_ad(client)
    _confirm_ad(client, ad_view_id, user_id)

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert start_response.status_code == 201
    session_id = start_response.json()["id"]

    # Sem expirar a sessão -- ainda dentro das 2h.
    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "mvp-early-collect-1"},
    )
    assert collect_response.status_code == 409

    status_response = client.get("/mining/status", params={"session_id": session_id}, headers=_auth_header())
    assert status_response.json()["status"] == "running"
    assert status_response.json()["ready_to_collect"] is False

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == Decimal("0")


def test_duplicate_collect_with_same_idempotency_key_does_not_duplicate_reward(
    client: TestClient, monkeypatch
):
    user_id = _register_and_login(client, monkeypatch, "uid-mvp-dup", "mvp-dup@example.com")
    cube_id = _get_starter_cube_id(client)
    _top_up_reward_fund(Decimal("100.00"))

    ad_view_id = _watch_ad(client)
    _confirm_ad(client, ad_view_id, user_id)

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    session_id = start_response.json()["id"]
    _expire_session_now(session_id)

    headers = {**_auth_header(), "Idempotency-Key": "mvp-dup-collect-1"}
    first = client.post("/mining/collect", json={"session_id": session_id}, headers=headers)
    assert first.status_code == 200
    reward_amount = Decimal(str(first.json()["reward_amount"]))

    # Retry com a mesma Idempotency-Key -- não sorteia nem credita de novo.
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


def test_concurrent_collect_requests_on_same_session_do_not_double_collect(
    client: TestClient, monkeypatch
):
    user_id = _register_and_login(client, monkeypatch, "uid-mvp-concurrent", "mvp-concurrent@example.com")
    cube_id = _get_starter_cube_id(client)
    _top_up_reward_fund(Decimal("100.00"))

    ad_view_id = _watch_ad(client)
    _confirm_ad(client, ad_view_id, user_id)

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    session_id = start_response.json()["id"]
    _expire_session_now(session_id)

    # TestClient é síncrono dentro de uma thread -- pra simular duas
    # requisições concorrentes de verdade (duas conexões de banco reais
    # disputando o lock de linha), chamamos o serviço diretamente com
    # sessões de banco separadas, uma por thread.
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

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == results[0]

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


def test_start_mining_without_ad_confirmation_is_rejected(client: TestClient, monkeypatch):
    _register_and_login(client, monkeypatch, "uid-mvp-unconfirmed", "mvp-unconfirmed@example.com")
    cube_id = _get_starter_cube_id(client)

    ad_view_id = _watch_ad(client)
    # Sem chamar _confirm_ad -- ad_view continua pending.

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert start_response.status_code == 400

    db = SessionLocal()
    try:
        sessions = db.query(MiningSession).filter(MiningSession.cube_id == cube_id).count()
    finally:
        db.close()
    assert sessions == 0


def test_insufficient_reward_fund_fails_safely(client: TestClient, monkeypatch):
    user_id = _register_and_login(client, monkeypatch, "uid-mvp-insufficient", "mvp-insufficient@example.com")
    cube_id = _get_starter_cube_id(client)
    # reward_fund fica em balance=0 (reset pela fixture de limpeza) -- não
    # damos top-up, então qualquer sorteio (mínimo R$0.10) excede
    # balance * margem de segurança.

    ad_view_id = _watch_ad(client)
    _confirm_ad(client, ad_view_id, user_id)

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    session_id = start_response.json()["id"]
    _expire_session_now(session_id)

    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "mvp-insufficient-collect-1"},
    )
    assert collect_response.status_code == 503

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

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == Decimal("0")
