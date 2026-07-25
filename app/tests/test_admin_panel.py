from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.core.efi import EfiApiError
from app.db.session import SessionLocal
from app.models.ledger_entry import LedgerEntryType
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


def _register_user(client: TestClient, monkeypatch, uid: str, email: str) -> int:
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify(uid, email))
    response = client.post("/auth/register", json={"pix_key": f"{uid}@example.com"}, headers=_auth_header())
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
