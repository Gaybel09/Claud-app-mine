from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.models.withdrawal import Withdrawal, WithdrawalStatus
from app.modules.pix import service as pix_service
from app.modules.wallet.service import create_ledger_entry
from app.models.ledger_entry import LedgerEntryType
from app.workers.tasks import reconcile_pending_withdrawals


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
    db = SessionLocal()
    try:
        withdrawal = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
        withdrawal.created_at = datetime.now(timezone.utc) - age
        db.commit()
    finally:
        db.close()


def test_reconcile_pending_withdrawals_only_touches_stale_processing_withdrawals(client: TestClient, monkeypatch):
    """pix.reconcile_pending_withdrawals (o worker periódico, seção 11
    correção v2) só deve mexer em saques parados em "processing" há mais de
    RECONCILE_AFTER_MINUTES -- um saque "processing" bem recente ainda pode
    ser confirmado pelo webhook a qualquer momento, então consultar a Efí
    de novo pra ele é só desperdício de chamada."""
    user_id = _register_user(client, monkeypatch, "uid-worker-1", "worker-1@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    stale_id = _create_withdrawal(client, "worker-stale-1")
    fresh_id = _create_withdrawal(client, "worker-fresh-1")

    _backdate(stale_id, timedelta(minutes=pix_service.RECONCILE_AFTER_MINUTES + 1))
    # fresh_id fica com created_at == agora (default), bem abaixo do corte.

    call_count = {"n": 0}

    def _get_send_status(id_envio):
        call_count["n"] += 1
        return {"status": "REALIZADO"}

    monkeypatch.setattr(pix_service.efi_client, "get_send_status", _get_send_status)

    reconcile_pending_withdrawals()

    assert call_count["n"] == 1

    db = SessionLocal()
    try:
        stale = db.query(Withdrawal).filter(Withdrawal.id == stale_id).first()
        fresh = db.query(Withdrawal).filter(Withdrawal.id == fresh_id).first()
        assert stale.status == WithdrawalStatus.PAID
        assert fresh.status == WithdrawalStatus.PROCESSING
    finally:
        db.close()


def test_reconcile_pending_withdrawals_ignores_pending_paid_and_failed(client: TestClient, monkeypatch):
    """Só "processing" é candidato -- "pending" (nunca chegou a ser enviado
    pra Efí, não tem efi_id_envio confirmado ainda pra esse fluxo) e os
    estados terminais (paid/failed) não devem gerar nenhuma chamada à Efí."""
    user_id = _register_user(client, monkeypatch, "uid-worker-2", "worker-2@example.com")
    _credit_balance(user_id, Decimal("100.00"))

    def _raise_send_pix(**kwargs):
        from app.core.efi import EfiApiError

        raise EfiApiError(500, "efi is down")

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _raise_send_pix)
    failed_id = _create_withdrawal(client, "worker-failed-1")
    _backdate(failed_id, timedelta(minutes=pix_service.RECONCILE_AFTER_MINUTES + 1))

    def _fail_if_called(id_envio):
        raise AssertionError("should not query Efi for a withdrawal that is not stale-processing")

    monkeypatch.setattr(pix_service.efi_client, "get_send_status", _fail_if_called)

    reconcile_pending_withdrawals()  # não deve levantar nem chamar a Efí

    db = SessionLocal()
    try:
        failed = db.query(Withdrawal).filter(Withdrawal.id == failed_id).first()
        assert failed.status == WithdrawalStatus.FAILED
    finally:
        db.close()
