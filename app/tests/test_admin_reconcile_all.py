from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.core.config import settings
from app.core.efi import EfiApiError
from app.db.session import SessionLocal
from app.models.withdrawal import Withdrawal, WithdrawalStatus
from app.modules.pix import service as pix_service
from app.modules.wallet.service import create_ledger_entry
from app.models.ledger_entry import LedgerEntryType

ADMIN_HEADER = "X-Admin-Token"


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
    response = client.post("/auth/register", json={"pix_key": f"{uid}@example.com"}, headers=_auth_header())
    assert response.status_code == 201
    return response.json()["id"]


def _credit_balance(user_id: int, amount: Decimal) -> None:
    db = SessionLocal()
    try:
        create_ledger_entry(db, user_id=user_id, type=LedgerEntryType.REWARD, amount=amount, reference_id="test-credit")
        db.commit()
    finally:
        db.close()


def _create_withdrawal(client: TestClient, idempotency_key: str, amount: str = "10.00") -> int:
    response = client.post(
        "/pix/withdraw",
        json={"amount": amount},
        headers={**_auth_header(), "Idempotency-Key": idempotency_key},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _backdate(withdrawal_id: int, age: timedelta) -> None:
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        withdrawal = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
        withdrawal.created_at = datetime.now(timezone.utc) - age
        db.commit()
    finally:
        db.close()


def test_reconcile_all_returns_404_when_token_not_configured(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", None)

    response = client.post("/admin/withdrawals/reconcile-all", headers={ADMIN_HEADER: "anything"})
    assert response.status_code == 404


def test_reconcile_all_rejects_wrong_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.post("/admin/withdrawals/reconcile-all", headers={ADMIN_HEADER: "wrong-token"})
    assert response.status_code == 403


def test_reconcile_all_works_without_enabling_diagnostic_endpoints(client: TestClient, monkeypatch):
    """Ao contrário de /admin/smoke-test/pix e /admin/register-efi-webhook,
    este endpoint precisa continuar acessível em produção real mesmo com
    ENABLE_DIAGNOSTIC_ENDPOINTS desligada -- é a ponte usada pelo GitHub
    Actions enquanto o worker de verdade não está aprovado."""
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "ENABLE_DIAGNOSTIC_ENDPOINTS", False)

    response = client.post("/admin/withdrawals/reconcile-all", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    assert response.json() == {"reconciled_count": 0, "withdrawals": []}


def test_reconcile_all_confirms_stale_processing_withdrawals_and_debits_balance(
    client: TestClient, monkeypatch
):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-all-1", "reconcile-all-1@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    stale_id = _create_withdrawal(client, "reconcile-all-stale-1")
    fresh_id = _create_withdrawal(client, "reconcile-all-fresh-1")
    _backdate(stale_id, timedelta(minutes=pix_service.RECONCILE_AFTER_MINUTES + 1))

    monkeypatch.setattr(pix_service.efi_client, "get_send_status", lambda id_envio: {"status": "REALIZADO"})

    response = client.post("/admin/withdrawals/reconcile-all", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["reconciled_count"] == 1
    assert body["withdrawals"] == [{"id": stale_id, "status": "paid", "failure_reason": None}]

    db = SessionLocal()
    try:
        fresh = db.query(Withdrawal).filter(Withdrawal.id == fresh_id).first()
        assert fresh.status == WithdrawalStatus.PROCESSING
    finally:
        db.close()

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-all-1", "reconcile-all-1@example.com"))
    balance = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance.json()["balance"])) == Decimal("90.00")


def test_reconcile_all_does_not_abort_the_batch_when_one_efi_query_fails(client: TestClient, monkeypatch):
    """Um saque com problema (ex: Efí fora do ar) não pode impedir os
    demais de serem reconciliados na mesma chamada -- mesma tolerância a
    falha do worker periódico."""
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-all-2", "reconcile-all-2@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    failing_id = _create_withdrawal(client, "reconcile-all-failing-1")
    ok_id = _create_withdrawal(client, "reconcile-all-ok-1")
    _backdate(failing_id, timedelta(minutes=pix_service.RECONCILE_AFTER_MINUTES + 1))
    _backdate(ok_id, timedelta(minutes=pix_service.RECONCILE_AFTER_MINUTES + 1))

    def _get_send_status(id_envio):
        if id_envio == pix_service.derive_id_envio("reconcile-all-failing-1"):
            raise EfiApiError(500, "efi is down")
        return {"status": "REALIZADO"}

    monkeypatch.setattr(pix_service.efi_client, "get_send_status", _get_send_status)

    response = client.post("/admin/withdrawals/reconcile-all", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["reconciled_count"] == 2

    db = SessionLocal()
    try:
        failing = db.query(Withdrawal).filter(Withdrawal.id == failing_id).first()
        ok = db.query(Withdrawal).filter(Withdrawal.id == ok_id).first()
        assert failing.status == WithdrawalStatus.PROCESSING  # sem confirmação, continua como estava
        assert ok.status == WithdrawalStatus.PAID
    finally:
        db.close()
