from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import efi, firebase
from app.core.efi import EfiApiError
from app.db.session import SessionLocal
from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.models.withdrawal import Withdrawal
from app.modules.pix import service as pix_service
from app.modules.wallet.service import create_ledger_entry


def _fake_verify(uid: str, email: str):
    def _verify(id_token: str) -> dict:
        if id_token != "valid-token":
            raise firebase.InvalidFirebaseTokenError("bad token")
        return {"uid": uid, "email": email}

    return _verify


def _auth_header(token: str = "valid-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_user(client: TestClient, monkeypatch, uid: str, email: str, pix_key: str = "user-pix-key@example.com") -> int:
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify(uid, email))
    response = client.post("/auth/register", json={"pix_key": pix_key}, headers=_auth_header())
    assert response.status_code == 201
    return response.json()["id"]


def _credit_balance(user_id: int, amount: Decimal) -> None:
    db = SessionLocal()
    try:
        create_ledger_entry(
            db, user_id=user_id, type=LedgerEntryType.REWARD, amount=amount, reference_id="test-credit"
        )
        db.commit()
    finally:
        db.close()


def test_withdraw_rejects_insufficient_balance(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-pix-insufficient", "pix-insufficient@example.com")

    def _fail_if_called(**kwargs):
        raise AssertionError("efi_client.send_pix should not be called when balance is insufficient")

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _fail_if_called)

    response = client.post(
        "/pix/withdraw",
        json={"amount": "50.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-insufficient-1"},
    )
    assert response.status_code == 400

    db = SessionLocal()
    try:
        assert db.query(Withdrawal).filter(Withdrawal.user_id == user_id).count() == 0
    finally:
        db.close()


def test_withdraw_idempotent_same_key_does_not_call_efi_twice(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-pix-idempotent", "pix-idempotent@example.com")
    _credit_balance(user_id, Decimal("100.00"))

    call_count = {"n": 0}

    def _fake_send_pix(**kwargs):
        call_count["n"] += 1
        return {"status": "EM_PROCESSAMENTO"}

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _fake_send_pix)

    headers = {**_auth_header(), "Idempotency-Key": "withdraw-dup-1"}
    body = {"amount": "30.00"}

    first = client.post("/pix/withdraw", json=body, headers=headers)
    assert first.status_code == 201
    first_id = first.json()["id"]
    assert first.json()["status"] == "processing"

    second = client.post("/pix/withdraw", json=body, headers=headers)
    assert second.status_code == 201
    assert second.json()["id"] == first_id

    assert call_count["n"] == 1

    db = SessionLocal()
    try:
        count = db.query(Withdrawal).filter(Withdrawal.user_id == user_id).count()
    finally:
        db.close()
    assert count == 1


def test_withdraw_efi_send_failure_marks_failed_without_debiting(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-pix-efi-fail", "pix-efi-fail@example.com")
    _credit_balance(user_id, Decimal("100.00"))

    def _raise(**kwargs):
        raise EfiApiError(500, "efi is down")

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _raise)

    response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-efi-fail-2"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == Decimal("100.00")


def test_webhook_confirms_and_debits_balance(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-pix-webhook", "pix-webhook@example.com")
    _credit_balance(user_id, Decimal("100.00"))

    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    withdraw_response = client.post(
        "/pix/withdraw",
        json={"amount": "40.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-webhook-1"},
    )
    assert withdraw_response.status_code == 201
    assert withdraw_response.json()["status"] == "processing"

    balance_before = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_before.json()["balance"])) == Decimal("100.00")

    webhook_response = client.post(
        "/pix/webhook",
        json={"status": "REALIZADO", "gnExtras": {"idEnvio": "withdraw-webhook-1"}},
    )
    assert webhook_response.status_code == 200

    balance_after = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_after.json()["balance"])) == Decimal("60.00")

    withdrawals_response = client.get("/pix/withdrawals", headers=_auth_header())
    assert withdrawals_response.json()[0]["status"] == "paid"


def test_duplicate_webhook_does_not_debit_twice(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-pix-dup-webhook", "pix-dup-webhook@example.com")
    _credit_balance(user_id, Decimal("100.00"))

    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    client.post(
        "/pix/withdraw",
        json={"amount": "25.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-dup-webhook-1"},
    )

    payload = {"status": "REALIZADO", "gnExtras": {"idEnvio": "withdraw-dup-webhook-1"}}
    first = client.post("/pix/webhook", json=payload)
    assert first.status_code == 200
    second = client.post("/pix/webhook", json=payload)
    assert second.status_code == 200

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == Decimal("75.00")

    db = SessionLocal()
    try:
        entries = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.user_id == user_id, LedgerEntry.type == LedgerEntryType.WITHDRAWAL)
            .all()
        )
    finally:
        db.close()
    assert len(entries) == 1


def test_webhook_rejected_status_marks_failed_without_debiting(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-pix-webhook-fail", "pix-webhook-fail@example.com")
    _credit_balance(user_id, Decimal("100.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    client.post(
        "/pix/withdraw",
        json={"amount": "20.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-webhook-fail-1"},
    )

    response = client.post(
        "/pix/webhook",
        json={"status": "NAO_REALIZADO", "gnExtras": {"idEnvio": "withdraw-webhook-fail-1"}},
    )
    assert response.status_code == 200

    withdrawals_response = client.get("/pix/withdrawals", headers=_auth_header())
    assert withdrawals_response.json()[0]["status"] == "failed"

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == Decimal("100.00")


def test_second_withdraw_rejected_while_first_still_pending(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-pix-double", "pix-double@example.com")
    _credit_balance(user_id, Decimal("50.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    first = client.post(
        "/pix/withdraw",
        json={"amount": "40.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-double-1"},
    )
    assert first.status_code == 201

    second = client.post(
        "/pix/withdraw",
        json={"amount": "40.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-double-2"},
    )
    assert second.status_code == 400


def test_withdraw_uses_registered_pix_key_when_omitted(client: TestClient, monkeypatch):
    user_id = _register_user(
        client, monkeypatch, "uid-pix-default-key", "pix-default-key@example.com", pix_key="registered@example.com"
    )
    _credit_balance(user_id, Decimal("50.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-default-key-1"},
    )
    assert response.status_code == 201
    assert response.json()["pix_key"] == "registered@example.com"


def test_list_withdrawals_returns_only_own(client: TestClient, monkeypatch):
    user_a_id = _register_user(client, monkeypatch, "uid-pix-list-a", "pix-list-a@example.com")
    _credit_balance(user_a_id, Decimal("50.00"))
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": "withdraw-list-a-1"},
    )

    _register_user(client, monkeypatch, "uid-pix-list-b", "pix-list-b@example.com")

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-pix-list-a", "pix-list-a@example.com"))
    response = client.get("/pix/withdrawals", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["user_id"] == user_a_id


def test_pix_health_ok_when_efi_auth_succeeds(client: TestClient, monkeypatch):
    monkeypatch.setattr(efi.efi_client, "check_auth", lambda: None)

    response = client.get("/pix/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_pix_health_returns_503_when_efi_not_configured(client: TestClient, monkeypatch):
    def _raise():
        raise efi.EfiConfigurationError("EFI_CLIENT_ID/EFI_CLIENT_SECRET not configured")

    monkeypatch.setattr(efi.efi_client, "check_auth", _raise)

    response = client.get("/pix/health")
    assert response.status_code == 503


def test_pix_health_returns_503_when_efi_auth_fails(client: TestClient, monkeypatch):
    def _raise():
        raise efi.EfiApiError(401, "invalid_client")

    monkeypatch.setattr(efi.efi_client, "check_auth", _raise)

    response = client.get("/pix/health")
    assert response.status_code == 503
    assert "401" in response.json()["detail"]


def test_pix_health_never_leaks_efi_response_body(client: TestClient, monkeypatch):
    """Mesmo se a Efí devolver algo sensível no corpo do erro (ex: eco de
    parte da credencial), a resposta do nosso endpoint nunca deve conter
    esse texto cru -- check_auth() só propaga status_code, nunca
    response.text."""

    class _FakeResponse:
        status_code = 401
        text = "invalid_client_secret=SECRETXYZ-should-never-leak"

        def json(self):
            return {}

    class _FakeHttpClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(efi.efi_client, "_http_client", lambda: _FakeHttpClient())

    response = client.get("/pix/health")
    assert response.status_code == 503
    assert "SECRETXYZ" not in response.text
    assert "invalid_client_secret" not in response.text
