from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.core.efi import EfiApiError
from app.db.session import SessionLocal
from app.models.ad_view import AdView, AdViewStatus
from app.models.cube import Cube, CubeType
from app.models.ledger_entry import LedgerEntryType
from app.models.mining_session import MiningSession
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.models.user import User
from app.modules.pix import service as pix_service
from app.modules.wallet.service import create_ledger_entry

ADMIN_HEADER = "X-Admin-Token"


def _fake_verify(uid: str, email: str):
    def _verify(id_token: str) -> dict:
        if id_token != "valid-token":
            raise firebase.InvalidFirebaseTokenError("bad token")
        return {"uid": uid, "email": email}

    return _verify


def _auth_header(token: str = "valid-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_user(client: TestClient, monkeypatch, uid: str, email: str, device_id: str | None = None) -> int:
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify(uid, email))
    headers = _auth_header()
    if device_id is not None:
        headers["X-Device-Id"] = device_id
    response = client.post("/auth/register", json={"pix_key": f"{uid}@example.com"}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def _make_admin(user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        user.is_admin = True
        db.commit()
    finally:
        db.close()


def _credit_balance(user_id: int, amount: Decimal) -> None:
    db = SessionLocal()
    try:
        create_ledger_entry(
            db, user_id=user_id, type=LedgerEntryType.REWARD, amount=amount, reference_id="test-credit"
        )
        db.commit()
    finally:
        db.close()


def _register_admin(client: TestClient, monkeypatch, uid: str, email: str) -> int:
    user_id = _register_user(client, monkeypatch, uid, email)
    _make_admin(user_id)
    # _register_user já deixou verify_firebase_token apontando pra este uid.
    return user_id


# --- Autenticação -----------------------------------------------------------


def test_admin_routes_reject_unauthenticated(client: TestClient):
    response = client.get("/admin/users")
    assert response.status_code == 401


def test_admin_routes_reject_non_admin_user(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-not-admin", "not-admin@example.com")

    response = client.get("/admin/users", headers=_auth_header())
    assert response.status_code == 403


def test_admin_routes_reject_blocked_admin(client: TestClient, monkeypatch):
    admin_id = _register_admin(client, monkeypatch, "uid-blocked-admin", "blocked-admin@example.com")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == admin_id).first()
        user.is_blocked = True
        db.commit()
    finally:
        db.close()

    response = client.get("/admin/users", headers=_auth_header())
    assert response.status_code == 403


# --- GET /admin/users --------------------------------------------------------


def test_list_users_returns_balance_and_status_paginated(client: TestClient, monkeypatch):
    admin_id = _register_admin(client, monkeypatch, "uid-admin-1", "admin1@example.com")
    other_id = _register_user(client, monkeypatch, "uid-other-1", "other1@example.com")
    _credit_balance(other_id, Decimal("42.50"))

    # A última chamada a _register_user deixou verify_firebase_token
    # apontando pro "other" -- volta a apontar pro admin antes de chamar
    # a rota autenticada como admin.
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-1", "admin1@example.com"))

    response = client.get("/admin/users?page=1&page_size=50", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert body["total"] == 2

    by_id = {item["id"]: item for item in body["items"]}
    assert Decimal(by_id[other_id]["balance"]) == Decimal("42.50")
    assert by_id[other_id]["is_blocked"] is False
    assert by_id[other_id]["is_admin"] is False
    assert by_id[admin_id]["is_admin"] is True
    assert "created_at" in by_id[other_id]


def test_list_users_pagination(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-page", "admin-page@example.com")
    for i in range(3):
        _register_user(client, monkeypatch, f"uid-page-{i}", f"page-{i}@example.com")
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-page", "admin-page@example.com"))

    response = client.get("/admin/users?page=1&page_size=2", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2


# --- block/unblock -----------------------------------------------------------


def test_block_and_unblock_user(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-block", "admin-block@example.com")
    target_id = _register_user(client, monkeypatch, "uid-target-block", "target-block@example.com")
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-block", "admin-block@example.com"))

    block_response = client.post(f"/admin/users/{target_id}/block", headers=_auth_header())
    assert block_response.status_code == 200
    assert block_response.json() == {"id": target_id, "is_blocked": True}

    # O usuário bloqueado não consegue mais usar a API normal.
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-target-block", "target-block@example.com"))
    blocked_call = client.get("/wallet/balance", headers=_auth_header())
    assert blocked_call.status_code == 403

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-block", "admin-block@example.com"))
    unblock_response = client.post(f"/admin/users/{target_id}/unblock", headers=_auth_header())
    assert unblock_response.status_code == 200
    assert unblock_response.json() == {"id": target_id, "is_blocked": False}

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-target-block", "target-block@example.com"))
    unblocked_call = client.get("/wallet/balance", headers=_auth_header())
    assert unblocked_call.status_code == 200


def test_block_nonexistent_user_returns_404(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-404", "admin-404@example.com")

    response = client.post("/admin/users/999999/block", headers=_auth_header())
    assert response.status_code == 404


# --- GET /admin/withdrawals ---------------------------------------------------


def test_list_withdrawals_across_all_users_with_status_filter(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-wd", "admin-wd@example.com")

    user_a = _register_user(client, monkeypatch, "uid-wd-a", "wd-a@example.com")
    _credit_balance(user_a, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-wd-a", "wd-a@example.com"))
    client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-wd-a-1"},
    )

    user_b = _register_user(client, monkeypatch, "uid-wd-b", "wd-b@example.com")
    _credit_balance(user_b, Decimal("100.00"))

    def _raise(**kwargs):
        raise EfiApiError(500, "efi is down")

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _raise)
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-wd-b", "wd-b@example.com"))
    client.post(
        "/pix/withdraw",
        json={"amount": "20.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-wd-b-1"},
    )

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-wd", "admin-wd@example.com"))

    all_response = client.get("/admin/withdrawals", headers=_auth_header())
    assert all_response.status_code == 200
    all_body = all_response.json()
    assert all_body["total"] == 2
    user_ids = {item["user_id"] for item in all_body["items"]}
    assert user_ids == {user_a, user_b}

    failed_response = client.get("/admin/withdrawals?status=failed", headers=_auth_header())
    assert failed_response.status_code == 200
    failed_body = failed_response.json()
    assert failed_body["total"] == 1
    assert failed_body["items"][0]["user_id"] == user_b
    assert failed_body["items"][0]["failure_reason"] == "HTTP 500: efi is down"

    processing_response = client.get("/admin/withdrawals?status=processing", headers=_auth_header())
    assert processing_response.json()["total"] == 1


def test_list_withdrawals_rejects_invalid_status(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-badstatus", "admin-badstatus@example.com")

    response = client.get("/admin/withdrawals?status=not-a-real-status", headers=_auth_header())
    assert response.status_code == 400


# --- POST /admin/withdrawals/{id}/approve ------------------------------------


def test_approve_withdrawal_marks_paid_and_debits_balance(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-approve", "admin-approve@example.com")

    user_id = _register_user(client, monkeypatch, "uid-approve-target", "approve-target@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-approve-target", "approve-target@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "30.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-approve-1"},
    )
    withdrawal_id = withdraw_response.json()["id"]
    assert withdraw_response.json()["status"] == "processing"

    balance_before = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_before.json()["balance"])) == Decimal("100.00")

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-approve", "admin-approve@example.com"))
    approve_response = client.post(f"/admin/withdrawals/{withdrawal_id}/approve", headers=_auth_header())
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "paid"

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-approve-target", "approve-target@example.com"))
    balance_after = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_after.json()["balance"])) == Decimal("70.00")


def test_approve_withdrawal_is_idempotent(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-approve-idem", "admin-approve-idem@example.com")
    user_id = _register_user(client, monkeypatch, "uid-approve-idem", "approve-idem@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-approve-idem", "approve-idem@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "15.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-approve-idem-1"},
    )
    withdrawal_id = withdraw_response.json()["id"]

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-approve-idem", "admin-approve-idem@example.com"))
    first = client.post(f"/admin/withdrawals/{withdrawal_id}/approve", headers=_auth_header())
    second = client.post(f"/admin/withdrawals/{withdrawal_id}/approve", headers=_auth_header())
    assert first.status_code == 200
    assert second.status_code == 200

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-approve-idem", "approve-idem@example.com"))
    balance = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance.json()["balance"])) == Decimal("85.00")


def test_approve_withdrawal_not_found_returns_404(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-404-wd", "admin-404-wd@example.com")

    response = client.post("/admin/withdrawals/999999/approve", headers=_auth_header())
    assert response.status_code == 404


def test_approve_already_failed_withdrawal_returns_400(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-approve-fail", "admin-approve-fail@example.com")
    user_id = _register_user(client, monkeypatch, "uid-approve-fail", "approve-fail@example.com")
    _credit_balance(user_id, Decimal("100.00"))

    def _raise(**kwargs):
        raise EfiApiError(500, "efi is down")

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _raise)
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-approve-fail", "approve-fail@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-approve-fail-1"},
    )
    withdrawal_id = withdraw_response.json()["id"]
    assert withdraw_response.json()["status"] == "failed"

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-approve-fail", "admin-approve-fail@example.com"))
    response = client.post(f"/admin/withdrawals/{withdrawal_id}/approve", headers=_auth_header())
    assert response.status_code == 400


# --- POST /admin/withdrawals/{id}/reconcile ----------------------------------


def test_reconcile_withdrawal_applies_paid_status_from_efi(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-reconcile-1", "admin-reconcile-1@example.com")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-1", "reconcile-1@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-1", "reconcile-1@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "30.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-reconcile-1"},
    )
    withdrawal_id = withdraw_response.json()["id"]
    assert withdraw_response.json()["status"] == "processing"

    monkeypatch.setattr(
        pix_service.efi_client, "get_send_status", lambda id_envio: {"status": "REALIZADO"}
    )
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-reconcile-1", "admin-reconcile-1@example.com"))
    reconcile_response = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert reconcile_response.status_code == 200
    assert reconcile_response.json()["status"] == "paid"

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-1", "reconcile-1@example.com"))
    balance = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance.json()["balance"])) == Decimal("70.00")


def test_reconcile_withdrawal_leaves_status_unchanged_when_still_processing(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-reconcile-2", "admin-reconcile-2@example.com")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-2", "reconcile-2@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-2", "reconcile-2@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-reconcile-2"},
    )
    withdrawal_id = withdraw_response.json()["id"]

    monkeypatch.setattr(
        pix_service.efi_client, "get_send_status", lambda id_envio: {"status": "EM_PROCESSAMENTO"}
    )
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-reconcile-2", "admin-reconcile-2@example.com"))
    response = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


def test_reconcile_withdrawal_always_queries_efi_and_never_double_debits_once_paid(
    client: TestClient, monkeypatch
):
    """Ao contrário do worker periódico, o endpoint admin sempre reconsulta
    a Efí de verdade quando chamado, mesmo que o saque já esteja pago --
    a segurança contra debitar duas vezes vem da própria idempotência de
    apply_efi_status, não de pular a chamada aqui."""
    _register_admin(client, monkeypatch, "uid-admin-reconcile-3", "admin-reconcile-3@example.com")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-3", "reconcile-3@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-3", "reconcile-3@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "20.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-reconcile-3"},
    )
    withdrawal_id = withdraw_response.json()["id"]

    call_count = {"n": 0}

    def _get_send_status(id_envio):
        call_count["n"] += 1
        return {"status": "REALIZADO"}

    monkeypatch.setattr(pix_service.efi_client, "get_send_status", _get_send_status)
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-reconcile-3", "admin-reconcile-3@example.com"))
    first = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert first.json()["status"] == "paid"

    second = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert second.status_code == 200
    assert second.json()["status"] == "paid"

    # A Efí foi consultada nas duas chamadas -- mas o saldo só foi debitado uma vez.
    assert call_count["n"] == 2

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-3", "reconcile-3@example.com"))
    balance = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance.json()["balance"])) == Decimal("80.00")


def test_reconcile_withdrawal_returns_503_when_efi_query_fails(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-reconcile-4", "admin-reconcile-4@example.com")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-4", "reconcile-4@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-4", "reconcile-4@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-reconcile-4"},
    )
    withdrawal_id = withdraw_response.json()["id"]

    def _raise(id_envio):
        raise EfiApiError(500, "efi is down")

    monkeypatch.setattr(pix_service.efi_client, "get_send_status", _raise)
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-reconcile-4", "admin-reconcile-4@example.com"))
    response = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert response.status_code == 503


def test_reconcile_withdrawal_populates_failure_reason_from_efi_error(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-reconcile-5", "admin-reconcile-5@example.com")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-5", "reconcile-5@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-5", "reconcile-5@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-reconcile-5"},
    )
    withdrawal_id = withdraw_response.json()["id"]

    monkeypatch.setattr(
        pix_service.efi_client,
        "get_send_status",
        lambda id_envio: {
            "status": "NAO_REALIZADO",
            "gnExtras": {"idEnvio": id_envio, "error": {"codigo": "PIX_KEY_INVALID", "motivo": "chave Pix inválida"}},
        },
    )
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-reconcile-5", "admin-reconcile-5@example.com"))
    response = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["failure_reason"] == "PIX_KEY_INVALID: chave Pix inválida"


def test_reconcile_withdrawal_backfills_failure_reason_when_previously_null(client: TestClient, monkeypatch):
    """Reconciliações antigas (antes deste fix) podiam marcar failed sem
    capturar o motivo -- uma nova chamada de reconcile deve reconsultar a
    Efí e preencher o motivo, mesmo com o saque já em estado terminal."""
    _register_admin(client, monkeypatch, "uid-admin-reconcile-6", "admin-reconcile-6@example.com")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-6", "reconcile-6@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-6", "reconcile-6@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-reconcile-6"},
    )
    withdrawal_id = withdraw_response.json()["id"]

    monkeypatch.setattr(
        pix_service.efi_client, "get_send_status", lambda id_envio: {"status": "NAO_REALIZADO"}
    )
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-reconcile-6", "admin-reconcile-6@example.com"))
    first = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert first.json()["status"] == "failed"
    assert first.json()["failure_reason"] is None

    monkeypatch.setattr(
        pix_service.efi_client,
        "get_send_status",
        lambda id_envio: {
            "status": "NAO_REALIZADO",
            "gnExtras": {"idEnvio": id_envio, "error": {"codigo": "SALDO_INSUFICIENTE", "motivo": "saldo insuficiente na conta pagadora"}},
        },
    )
    second = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert second.status_code == 200
    assert second.json()["status"] == "failed"
    assert second.json()["failure_reason"] == "SALDO_INSUFICIENTE: saldo insuficiente na conta pagadora"


def test_reconcile_withdrawal_still_queries_efi_again_once_failure_reason_is_set(
    client: TestClient, monkeypatch
):
    """Uma segunda chamada explícita do admin ainda consulta a Efí de novo
    (não é pulada só porque já tem um failure_reason salvo) -- só não muda
    nada porque o saque já está em estado terminal."""
    _register_admin(client, monkeypatch, "uid-admin-reconcile-7", "admin-reconcile-7@example.com")
    user_id = _register_user(client, monkeypatch, "uid-reconcile-7", "reconcile-7@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-reconcile-7", "reconcile-7@example.com"))
    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "admin-reconcile-7"},
    )
    withdrawal_id = withdraw_response.json()["id"]

    call_count = {"n": 0}

    def _get_send_status(id_envio):
        call_count["n"] += 1
        return {
            "status": "NAO_REALIZADO",
            "gnExtras": {"idEnvio": id_envio, "error": {"codigo": "X", "motivo": "y"}},
        }

    monkeypatch.setattr(pix_service.efi_client, "get_send_status", _get_send_status)
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-reconcile-7", "admin-reconcile-7@example.com"))
    client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())

    response = client.post(f"/admin/withdrawals/{withdrawal_id}/reconcile", headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["failure_reason"] == "X: y"
    assert call_count["n"] == 2


def test_reconcile_withdrawal_not_found_returns_404(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-reconcile-404", "admin-reconcile-404@example.com")

    response = client.post("/admin/withdrawals/999999/reconcile", headers=_auth_header())
    assert response.status_code == 404


def test_reconcile_withdrawal_requires_admin_login(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-not-admin-reconcile", "not-admin-reconcile@example.com")

    response = client.post("/admin/withdrawals/1/reconcile", headers=_auth_header())
    assert response.status_code == 403


# --- GET /admin/fund ----------------------------------------------------------


def test_fund_status_reports_low_balance_alert(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-fund", "admin-fund@example.com")

    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_FUND_LOW_THRESHOLD", Decimal("50.00"))

    # A fixture _clean_tables reseta reward_fund pra 0 depois de cada teste,
    # e o começa em 0 aqui também -- abaixo do threshold.
    low_response = client.get("/admin/fund", headers=_auth_header())
    assert low_response.status_code == 200
    low_body = low_response.json()
    assert Decimal(low_body["balance"]) == Decimal("0")
    assert low_body["low_balance_alert"] is True
    assert Decimal(low_body["low_balance_threshold"]) == Decimal("50.00")

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        fund.balance = Decimal("100.00")
        fund.total_in = Decimal("100.00")
        db.commit()
    finally:
        db.close()

    healthy_response = client.get("/admin/fund", headers=_auth_header())
    healthy_body = healthy_response.json()
    assert Decimal(healthy_body["balance"]) == Decimal("100.00")
    assert Decimal(healthy_body["total_in"]) == Decimal("100.00")
    assert healthy_body["low_balance_alert"] is False


# --- POST /admin/fund/deposit -------------------------------------------------


def test_deposit_to_fund_increases_balance_and_total_in(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-deposit", "admin-deposit@example.com")

    response = client.post("/admin/fund/deposit", json={"amount": "250.00"}, headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["balance"]) == Decimal("250.00")
    assert Decimal(body["total_in"]) == Decimal("250.00")

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        assert fund.balance == Decimal("250.00")
        assert fund.total_in == Decimal("250.00")
    finally:
        db.close()


def test_deposit_to_fund_accumulates_across_multiple_deposits(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-deposit-2", "admin-deposit-2@example.com")

    client.post("/admin/fund/deposit", json={"amount": "100.00"}, headers=_auth_header())
    second = client.post("/admin/fund/deposit", json={"amount": "50.00"}, headers=_auth_header())

    assert Decimal(second.json()["balance"]) == Decimal("150.00")
    assert Decimal(second.json()["total_in"]) == Decimal("150.00")


def test_deposit_to_fund_does_not_touch_total_out(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-deposit-3", "admin-deposit-3@example.com")

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        fund.balance = Decimal("10.00")
        fund.total_out = Decimal("40.00")
        db.commit()
    finally:
        db.close()

    response = client.post("/admin/fund/deposit", json={"amount": "60.00"}, headers=_auth_header())
    assert Decimal(response.json()["balance"]) == Decimal("70.00")
    assert Decimal(response.json()["total_out"]) == Decimal("40.00")


def test_deposit_to_fund_rejects_zero_or_negative_amount(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-deposit-4", "admin-deposit-4@example.com")

    zero_response = client.post("/admin/fund/deposit", json={"amount": "0"}, headers=_auth_header())
    assert zero_response.status_code == 400

    negative_response = client.post(
        "/admin/fund/deposit", json={"amount": "-10.00"}, headers=_auth_header()
    )
    assert negative_response.status_code == 400

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        assert fund.balance == Decimal("0")
    finally:
        db.close()


def test_deposit_to_fund_requires_admin_login(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-not-admin-deposit", "not-admin-deposit@example.com")

    response = client.post("/admin/fund/deposit", json={"amount": "100.00"}, headers=_auth_header())
    assert response.status_code == 403


def test_deposit_to_fund_unlocks_the_full_collect_flow(client: TestClient, monkeypatch):
    """Prova o cenário real reportado: coleta falhando com 'reward fund
    unavailable' por saldo insuficiente, resolvido depositando no fundo
    via este endpoint -- sem precisar inserir nada direto no banco."""
    _register_admin(client, monkeypatch, "uid-admin-deposit-5", "admin-deposit-5@example.com")

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-collect-flow", "collect-flow@example.com"))
    register_response = client.post("/auth/register", json={}, headers=_auth_header())
    user_id = register_response.json()["id"]

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

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    session_id = start_response.json()["id"]

    db = SessionLocal()
    try:
        session = db.query(MiningSession).filter(MiningSession.id == session_id).first()
        session.ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    # reward_fund começa em 0 (fixture) -- a coleta falha por saldo insuficiente.
    failing_collect = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "collect-flow-1"},
    )
    assert failing_collect.status_code == 503

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-deposit-5", "admin-deposit-5@example.com"))
    deposit_response = client.post("/admin/fund/deposit", json={"amount": "100.00"}, headers=_auth_header())
    assert deposit_response.status_code == 200

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-collect-flow", "collect-flow@example.com"))
    successful_collect = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "collect-flow-1"},
    )
    assert successful_collect.status_code == 200
    assert successful_collect.json()["status"] == "collected"


# --- POST /admin/fund/adjust --------------------------------------------------


def test_adjust_fund_with_positive_amount_increases_balance(client: TestClient, monkeypatch):
    admin_id = _register_admin(client, monkeypatch, "uid-admin-adjust-1", "admin-adjust-1@example.com")

    response = client.post(
        "/admin/fund/adjust",
        json={"amount": "25.00", "reason": "aporte esquecido de registrar"},
        headers=_auth_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["amount"]) == Decimal("25.00")
    assert body["reason"] == "aporte esquecido de registrar"
    assert Decimal(body["balance_after"]) == Decimal("25.00")
    assert body["admin_user_id"] == admin_id

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        assert fund.balance == Decimal("25.00")
        assert fund.total_adjustments == Decimal("25.00")
    finally:
        db.close()


def test_adjust_fund_with_negative_amount_decreases_balance(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-adjust-2", "admin-adjust-2@example.com")

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        fund.balance = Decimal("100.00")
        fund.total_in = Decimal("100.00")
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/admin/fund/adjust",
        json={"amount": "-15.00", "reason": "depósito digitado errado (100 em vez de 85)"},
        headers=_auth_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["amount"]) == Decimal("-15.00")
    assert Decimal(body["balance_after"]) == Decimal("85.00")

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        assert fund.balance == Decimal("85.00")
        assert fund.total_adjustments == Decimal("-15.00")
        # total_in não deve ser tocado por um ajuste -- continua refletindo
        # só o depósito real que já tinha acontecido.
        assert fund.total_in == Decimal("100.00")
    finally:
        db.close()


def test_adjust_fund_rejects_zero_amount(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-adjust-3", "admin-adjust-3@example.com")

    response = client.post(
        "/admin/fund/adjust", json={"amount": "0", "reason": "sem motivo real"}, headers=_auth_header()
    )
    assert response.status_code == 400


def test_adjust_fund_rejects_blank_reason(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-adjust-4", "admin-adjust-4@example.com")

    blank_response = client.post(
        "/admin/fund/adjust", json={"amount": "10.00", "reason": ""}, headers=_auth_header()
    )
    assert blank_response.status_code == 400

    whitespace_response = client.post(
        "/admin/fund/adjust", json={"amount": "10.00", "reason": "   "}, headers=_auth_header()
    )
    assert whitespace_response.status_code == 400

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        assert fund.balance == Decimal("0")
    finally:
        db.close()


def test_adjust_fund_does_not_touch_total_in_or_total_out(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-adjust-5", "admin-adjust-5@example.com")

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        fund.balance = Decimal("50.00")
        fund.total_in = Decimal("70.00")
        fund.total_out = Decimal("20.00")
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/admin/fund/adjust", json={"amount": "5.00", "reason": "correção pontual"}, headers=_auth_header()
    )
    assert response.status_code == 200

    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
        assert fund.balance == Decimal("55.00")
        assert fund.total_in == Decimal("70.00")
        assert fund.total_out == Decimal("20.00")
        assert fund.total_adjustments == Decimal("5.00")
    finally:
        db.close()


def test_adjust_fund_requires_admin_login(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-not-admin-adjust", "not-admin-adjust@example.com")

    response = client.post(
        "/admin/fund/adjust", json={"amount": "10.00", "reason": "teste"}, headers=_auth_header()
    )
    assert response.status_code == 403


def test_fund_status_reports_total_adjustments(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-adjust-6", "admin-adjust-6@example.com")

    client.post(
        "/admin/fund/adjust", json={"amount": "-3.50", "reason": "correção"}, headers=_auth_header()
    )
    response = client.get("/admin/fund", headers=_auth_header())
    assert Decimal(response.json()["total_adjustments"]) == Decimal("-3.50")


# --- GET /admin/fund/adjustments -----------------------------------------------


def test_list_fund_adjustments_orders_most_recent_first(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-adjust-list-1", "admin-adjust-list-1@example.com")

    client.post(
        "/admin/fund/adjust", json={"amount": "10.00", "reason": "primeiro ajuste"}, headers=_auth_header()
    )
    client.post(
        "/admin/fund/adjust", json={"amount": "-4.00", "reason": "segundo ajuste"}, headers=_auth_header()
    )

    response = client.get("/admin/fund/adjustments", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["reason"] for item in body["items"]] == ["segundo ajuste", "primeiro ajuste"]


def test_list_fund_adjustments_paginates(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-adjust-list-2", "admin-adjust-list-2@example.com")

    for i in range(3):
        client.post(
            "/admin/fund/adjust", json={"amount": "1.00", "reason": f"ajuste {i}"}, headers=_auth_header()
        )

    response = client.get("/admin/fund/adjustments?page=1&page_size=2", headers=_auth_header())
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

    second_page = client.get("/admin/fund/adjustments?page=2&page_size=2", headers=_auth_header())
    assert len(second_page.json()["items"]) == 1


def test_list_fund_adjustments_requires_admin_login(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-not-admin-adjust-list", "not-admin-adjust-list@example.com")

    response = client.get("/admin/fund/adjustments", headers=_auth_header())
    assert response.status_code == 403


# --- GET /admin/users/{id}/devices -------------------------------------------


def test_user_devices_reports_no_sharing_when_device_is_unique(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-devices-1", "admin-devices-1@example.com")
    target_id = _register_user(
        client, monkeypatch, "uid-devices-solo", "devices-solo@example.com", device_id="device-solo"
    )
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-devices-1", "admin-devices-1@example.com"))

    response = client.get(f"/admin/users/{target_id}/devices", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == target_id
    assert body["device_id"] == "device-solo"
    assert body["shared_user_count"] == 1
    assert [u["id"] for u in body["shared_users"]] == [target_id]


def test_user_devices_reports_null_when_no_device_id_was_sent(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-devices-2", "admin-devices-2@example.com")
    target_id = _register_user(client, monkeypatch, "uid-devices-none", "devices-none@example.com")
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-devices-2", "admin-devices-2@example.com"))

    response = client.get(f"/admin/users/{target_id}/devices", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] is None
    assert body["shared_user_count"] == 0
    assert body["shared_users"] == []


def test_user_devices_groups_users_sharing_the_same_device(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-devices-3", "admin-devices-3@example.com")
    user_a = _register_user(
        client, monkeypatch, "uid-devices-a", "devices-a@example.com", device_id="shared-device-1"
    )
    user_b = _register_user(
        client, monkeypatch, "uid-devices-b", "devices-b@example.com", device_id="shared-device-1"
    )
    user_c = _register_user(
        client, monkeypatch, "uid-devices-c", "devices-c@example.com", device_id="shared-device-1"
    )
    # Um usuário com device_id diferente não deve aparecer no agrupamento.
    _register_user(client, monkeypatch, "uid-devices-other", "devices-other@example.com", device_id="another-device")

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-admin-devices-3", "admin-devices-3@example.com"))

    response = client.get(f"/admin/users/{user_b}/devices", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["device_id"] == "shared-device-1"
    assert body["shared_user_count"] == 3
    assert {u["id"] for u in body["shared_users"]} == {user_a, user_b, user_c}

    # Consultar qualquer um dos três retorna o mesmo agrupamento.
    response_from_a = client.get(f"/admin/users/{user_a}/devices", headers=_auth_header())
    assert {u["id"] for u in response_from_a.json()["shared_users"]} == {user_a, user_b, user_c}


def test_user_devices_returns_404_for_nonexistent_user(client: TestClient, monkeypatch):
    _register_admin(client, monkeypatch, "uid-admin-devices-404", "admin-devices-404@example.com")

    response = client.get("/admin/users/999999/devices", headers=_auth_header())
    assert response.status_code == 404


# --- POST /admin/promote-user, /admin/demote-user (ADMIN_SMOKE_TEST_TOKEN) --


def test_promote_and_demote_user_via_admin_token(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    user_id = _register_user(client, monkeypatch, "uid-promote-target", "promote-target@example.com")

    promote_response = client.post(
        f"/admin/promote-user/{user_id}", headers={ADMIN_HEADER: "the-real-token"}
    )
    assert promote_response.status_code == 200
    assert promote_response.json() == {
        "id": user_id,
        "email": "promote-target@example.com",
        "is_admin": True,
    }

    # Agora consegue acessar o painel admin de verdade.
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-promote-target", "promote-target@example.com"))
    admin_call = client.get("/admin/users", headers=_auth_header())
    assert admin_call.status_code == 200

    demote_response = client.post(
        f"/admin/demote-user/{user_id}", headers={ADMIN_HEADER: "the-real-token"}
    )
    assert demote_response.status_code == 200
    assert demote_response.json()["is_admin"] is False

    demoted_call = client.get("/admin/users", headers=_auth_header())
    assert demoted_call.status_code == 403


def test_promote_user_returns_404_when_not_configured(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", None)
    response = client.post("/admin/promote-user/1", headers={ADMIN_HEADER: "anything"})
    assert response.status_code == 404


def test_promote_nonexistent_user_returns_404(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    response = client.post("/admin/promote-user/999999", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 404
