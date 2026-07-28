import re
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


def _efi_id_envio_for(idempotency_key: str) -> str:
    """A Efí exige idEnvio alfanumérico -- o webhook de teste precisa usar o
    mesmo valor derivado que o backend realmente envia (ver
    app.core.efi.derive_id_envio), não a idempotency_key crua."""
    return efi.derive_id_envio(idempotency_key)


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
    # failure_reason não é exposto na API pública (WithdrawalRead) -- só via
    # admin/smoke-test -- mas fica salvo na linha para diagnóstico.
    assert "failure_reason" not in response.json()

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == Decimal("100.00")

    db = SessionLocal()
    try:
        withdrawal = db.query(Withdrawal).filter(Withdrawal.user_id == user_id).first()
        assert withdrawal.failure_reason == "HTTP 500: efi is down"
    finally:
        db.close()


def test_send_pix_receives_alphanumeric_id_envio_derived_from_idempotency_key(
    client: TestClient, monkeypatch
):
    """A Efí rejeita idEnvio com hífen (só aceita ^[a-zA-Z0-9]{1,35}$), mas
    nossa Idempotency-Key é escolhida pelo cliente e normalmente tem hífens
    (ex: um UUID) -- send_pix precisa receber um id_envio já derivado, nunca
    a idempotency_key crua."""
    user_id = _register_user(client, monkeypatch, "uid-pix-id-envio", "pix-id-envio@example.com")
    _credit_balance(user_id, Decimal("50.00"))

    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return {"status": "EM_PROCESSAMENTO"}

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _capture)

    raw_idempotency_key = "withdraw-with-hyphens-1234-5678"
    response = client.post(
        "/pix/withdraw",
        json={"amount": "10.00"},
        headers={**_auth_header(), "Idempotency-Key": raw_idempotency_key},
    )
    assert response.status_code == 201

    id_envio = captured["id_envio"]
    assert re.fullmatch(r"[a-zA-Z0-9]{1,35}", id_envio)
    assert id_envio == efi.derive_id_envio(raw_idempotency_key)


def test_derive_id_envio_is_deterministic_and_alphanumeric():
    key = "some-uuid-1234-5678-abcd"
    first = efi.derive_id_envio(key)
    second = efi.derive_id_envio(key)

    assert first == second
    assert re.fullmatch(r"[a-zA-Z0-9]{1,35}", first)
    assert efi.derive_id_envio("a-different-key") != first


def test_failure_reason_from_get_status_reads_root_level_motivo():
    """Documentado oficialmente pela Efí (dev.efipay.com.br/en/docs/api-pix/
    gestao-de-pix/) para a resposta de consulta de status: {"status":
    "NAO_REALIZADO", "motivo": "..."} -- campo na raiz, não dentro de
    gnExtras.error (que é a forma usada pelo webhook, não confirmada nesta
    consulta)."""
    result = {"status": "NAO_REALIZADO", "motivo": "Negado por timeout"}
    assert pix_service.failure_reason_from_get_status(result) == "Negado por timeout"


def test_failure_reason_from_get_status_falls_back_to_gn_extras_error():
    result = {
        "status": "NAO_REALIZADO",
        "gnExtras": {"idEnvio": "abc123", "error": {"codigo": "X", "motivo": "y"}},
    }
    assert pix_service.failure_reason_from_get_status(result) == "X: y"


def test_failure_reason_from_get_status_returns_none_for_real_withdrawal_8_response():
    """Resposta real registrada nos logs (após o fix de logging) para o
    saque #8 -- NAO_REALIZADO sem "motivo" na raiz nem gnExtras.error, ou
    seja, a Efí não devolveu o motivo real por esta via para este saque
    específico. failure_reason continua nulo -- o único jeito de saber o
    motivo real de #8 é olhando o extrato/dashboard da própria Efí."""
    result = {
        "endToEndId": "E09089356202607280925APIe2c80f6f",
        "idEnvio": "2b0fd66321734d97388de5cac7fc3194",
        "valor": "0.60",
        "chave": "b52690c7-edf9-4fe9-9711-e4b527d03efc",
        "status": "NAO_REALIZADO",
        "horario": {},
    }
    assert pix_service.failure_reason_from_get_status(result) is None


def test_webhook_get_verification_check_returns_200(client: TestClient):
    """A Efí checa se a URL do webhook responde antes de aceitar o
    cadastro (PUT /v2/webhook/:chave) -- essa checagem pode usar GET, que
    a notificação real (sempre POST) nunca usa."""
    response = client.get("/pix/webhook")
    assert response.status_code == 200


def test_webhook_empty_post_body_is_treated_as_verification_ping(client: TestClient):
    """A checagem de acessibilidade da Efí antes de cadastrar o webhook pode
    mandar um POST com corpo vazio -- isso não deve ser tratado como uma
    notificação de pagamento inválida (422), e sim como um ping, com 200."""
    response = client.post("/pix/webhook", content=b"")
    assert response.status_code == 200


def test_webhook_post_body_not_matching_notification_shape_is_treated_as_ping(client: TestClient):
    """Um corpo que não bate com o formato de notificação real (ex: sem
    "status", ou nem é JSON) é tratado como ping de verificação -- 200, não
    422 -- sem processar nada como pagamento."""
    response = client.post("/pix/webhook", json={"ping": True})
    assert response.status_code == 200

    response = client.post(
        "/pix/webhook", content=b"not json at all", headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 200


def test_webhook_real_payload_missing_id_envio_still_rejected(client: TestClient):
    """Um payload que TEM o formato de notificação real (passa na validação
    Pydantic -- "status" presente) mas sem gnExtras.idEnvio continua sendo
    rejeitado com 400, igual antes -- a tolerância a "ping" não enfraquece a
    validação de um payload que é mesmo uma notificação."""
    response = client.post("/pix/webhook", json={"status": "REALIZADO"})
    assert response.status_code == 400


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
        json={"status": "REALIZADO", "gnExtras": {"idEnvio": _efi_id_envio_for("withdraw-webhook-1")}},
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

    payload = {
        "status": "REALIZADO",
        "gnExtras": {"idEnvio": _efi_id_envio_for("withdraw-dup-webhook-1")},
    }
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
        json={
            "status": "NAO_REALIZADO",
            "gnExtras": {
                "idEnvio": _efi_id_envio_for("withdraw-webhook-fail-1"),
                "error": {"codigo": "PIX_KEY_INVALID", "origem": "PSP", "motivo": "chave Pix inexistente"},
            },
        },
    )
    assert response.status_code == 200

    withdrawals_response = client.get("/pix/withdrawals", headers=_auth_header())
    assert withdrawals_response.json()[0]["status"] == "failed"
    assert "failure_reason" not in withdrawals_response.json()[0]

    balance_response = client.get("/wallet/balance", headers=_auth_header())
    assert Decimal(str(balance_response.json()["balance"])) == Decimal("100.00")

    db = SessionLocal()
    try:
        withdrawal = db.query(Withdrawal).filter(Withdrawal.user_id == user_id).first()
        assert withdrawal.failure_reason == "PIX_KEY_INVALID: chave Pix inexistente"
    finally:
        db.close()


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


def test_register_webhook_ignores_cached_token_and_requests_a_fresh_one(monkeypatch):
    """Adicionar um escopo novo (ex: "Alterar Webhooks") na aplicação Efí não
    invalida um token já emitido -- um token cacheado de uma chamada
    anterior no mesmo processo continuaria com os escopos antigos e a Efí
    rejeitaria com insufficient_scope. register_webhook precisa sempre pedir
    um token novo, do mesmo jeito que check_auth já faz."""
    monkeypatch.setattr(efi.settings, "EFI_CLIENT_ID", "id")
    monkeypatch.setattr(efi.settings, "EFI_CLIENT_SECRET", "secret")

    client = efi.EfiPixClient()
    client._access_token = "stale-token-from-before-scope-change"

    token_requests = {"n": 0}

    class _FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class _FakeHttpClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, path, **kwargs):
            assert path == "/oauth/token"
            token_requests["n"] += 1
            return _FakeResponse({"access_token": f"fresh-token-{token_requests['n']}"})

        def put(self, path, **kwargs):
            assert path == "/v2/webhook/payer@example.com"
            assert kwargs["headers"]["Authorization"] == "Bearer fresh-token-1"
            return _FakeResponse({"webhookUrl": kwargs["json"]["webhookUrl"]})

    monkeypatch.setattr(client, "_http_client", lambda: _FakeHttpClient())

    result = client.register_webhook(
        pix_key="payer@example.com", webhook_url="https://host/pix/webhook"
    )

    assert token_requests["n"] == 1
    assert result == {"webhookUrl": "https://host/pix/webhook"}
    # O cache é atualizado com o token novo, não deixado com o antigo.
    assert client._access_token == "fresh-token-1"


def test_register_webhook_sends_skip_mtls_checking_header(monkeypatch):
    """A Efí, por padrão, exige que o próprio servidor de webhook valide o
    certificado mTLS dela nas notificações recebidas -- não temos isso
    configurado (hospedado no Render), então o cadastro do webhook precisa
    ir com x-skip-mtls-checking: true (dev.efipay.com.br/docs/api-pix/
    webhooks#entendendo-o-padrão-mtls), senão a Efí espera validar mTLS de
    entrada que nunca vai bater."""
    monkeypatch.setattr(efi.settings, "EFI_CLIENT_ID", "id")
    monkeypatch.setattr(efi.settings, "EFI_CLIENT_SECRET", "secret")

    client = efi.EfiPixClient()
    captured_headers = {}

    class _FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    class _FakeHttpClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, path, **kwargs):
            return _FakeResponse({"access_token": "token"})

        def put(self, path, **kwargs):
            captured_headers.update(kwargs["headers"])
            return _FakeResponse({"webhookUrl": kwargs["json"]["webhookUrl"]})

    monkeypatch.setattr(client, "_http_client", lambda: _FakeHttpClient())

    client.register_webhook(pix_key="payer@example.com", webhook_url="https://host/pix/webhook")

    assert captured_headers["x-skip-mtls-checking"] == "true"
