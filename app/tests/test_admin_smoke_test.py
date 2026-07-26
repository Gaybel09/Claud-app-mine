import re
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.modules.admin import smoke_test as admin_smoke_test
from app.modules.pix import service as pix_service

ADMIN_HEADER = "X-Admin-Token"


@pytest.fixture(autouse=True)
def _enable_diagnostic_endpoints(monkeypatch):
    """Estes testes exercitam o comportamento real de /admin/smoke-test/pix
    (token, passos do fluxo, etc) -- não o novo gate ENABLE_DIAGNOSTIC_ENDPOINTS
    em si (default False, coberto por
    test_smoke_test_returns_404_when_diagnostics_disabled_even_with_valid_token
    logo abaixo, que desliga de volta explicitamente)."""
    monkeypatch.setattr(settings, "ENABLE_DIAGNOSTIC_ENDPOINTS", True)


def test_smoke_test_returns_404_when_not_configured(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", None)

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "anything"})
    assert response.status_code == 404


def test_smoke_test_returns_404_when_diagnostics_disabled_even_with_valid_token(
    client: TestClient, monkeypatch
):
    """Prova a segunda camada de proteção (ENABLE_DIAGNOSTIC_ENDPOINTS,
    default False): mesmo com o token certo, a rota continua 404 até essa
    variável ser explicitamente ligada -- o token vazar/ser adivinhado
    sozinho não basta pra acessar a rota."""
    monkeypatch.setattr(settings, "ENABLE_DIAGNOSTIC_ENDPOINTS", False)
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 404


def test_smoke_test_rejects_missing_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get("/admin/smoke-test/pix")
    assert response.status_code == 403


def test_smoke_test_rejects_wrong_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "wrong-token"})
    assert response.status_code == 403


def test_smoke_test_rejects_wrong_query_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get("/admin/smoke-test/pix?token=wrong-token")
    assert response.status_code == 403


def test_smoke_test_accepts_query_token_without_header(client: TestClient, monkeypatch):
    # Cenário do navegador de celular: sem acesso a curl/terminal para
    # setar headers, só a URL.
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", None)

    response = client.get("/admin/smoke-test/pix?token=the-real-token")
    assert response.status_code == 200
    assert response.json()["overall"] == "not_configured"


def test_smoke_test_reports_not_configured_when_no_payer_pix_key(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", None)

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    assert response.json()["overall"] == "not_configured"


def test_smoke_test_runs_all_steps_and_cleans_up(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()

    assert body["overall"] == "ok"
    steps = body["steps"]
    assert steps["register"]["ok"] is True
    assert steps["cube"]["ok"] is True
    assert steps["cube"]["type"] == "comum"
    assert steps["ads"]["ok"] is True
    assert steps["ads"]["status"] == "confirmed"
    assert steps["mining"]["ok"] is True
    reward_amount = Decimal(steps["mining"]["reward_amount"])
    assert Decimal("0.10") <= reward_amount <= Decimal("1.00")
    assert steps["wallet_balance"]["ok"] is True
    assert Decimal(steps["wallet_balance"]["balance"]) == reward_amount
    assert steps["pix_withdraw"]["ok"] is True
    assert steps["pix_withdraw"]["status"] == "processing"
    assert steps["pix_withdraw"]["pix_key"] == admin_smoke_test.EFI_SANDBOX_HOMOLOGATION_PIX_KEY
    assert re.fullmatch(r"[a-zA-Z0-9]{1,35}", steps["pix_withdraw"]["efi_id_envio"])
    assert steps["pix_withdraw"]["failure_reason"] is None
    assert steps["pix_withdrawals_list"]["ok"] is True
    assert steps["pix_withdrawals_list"]["final_status"] == "processing"
    assert steps["pix_withdrawals_list"]["final_failure_reason"] is None
    # Sem ?force_reconcile=true, a etapa de reconciliação nem roda.
    assert "pix_reconcile" not in steps


def test_smoke_test_withdraw_always_uses_efi_sandbox_homologation_pix_key(
    client: TestClient, monkeypatch
):
    """Independente de EFI_PAYER_PIX_KEY (ou qualquer outra config), o saque
    de teste tem que ir pra efipay@sejaefi.com.br -- a única chave que a
    Efí confirma/rejeita de verdade em sandbox
    (dev.efipay.com.br/docs/api-pix/envio-pagamento-pix). Qualquer outra
    chave, mesmo uma chave real válida, dá "chave_favorecido_nao_encontrada"."""
    assert admin_smoke_test.EFI_SANDBOX_HOMOLOGATION_PIX_KEY == "efipay@sejaefi.com.br"

    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "some-other-payer-key@example.com")

    captured = {}

    def _fake_send_pix(**kwargs):
        captured.update(kwargs)
        return {"status": "EM_PROCESSAMENTO"}

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _fake_send_pix)

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200

    assert captured["favorecido_chave"] == "efipay@sejaefi.com.br"


def test_smoke_test_force_reconcile_confirms_payment(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})
    monkeypatch.setattr(pix_service.efi_client, "get_send_status", lambda id_envio: {"status": "REALIZADO"})

    response = client.get(
        "/admin/smoke-test/pix?force_reconcile=true", headers={ADMIN_HEADER: "the-real-token"}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["overall"] == "ok"
    steps = body["steps"]
    assert steps["pix_withdraw"]["status"] == "processing"
    assert steps["pix_reconcile"]["ok"] is True
    assert steps["pix_reconcile"]["status_before"] == "processing"
    assert steps["pix_reconcile"]["status_after"] == "paid"
    assert steps["pix_reconcile"]["failure_reason"] is None
    assert steps["pix_withdrawals_list"]["final_status"] == "paid"


def test_smoke_test_force_reconcile_tolerates_efi_query_failure(client: TestClient, monkeypatch):
    """Se a consulta de status na Efí falhar durante a reconciliação forçada,
    o passo não derruba o smoke test -- mesmo comportamento tolerante do
    worker periódico (reconcile_withdrawal só loga e segue)."""
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")
    monkeypatch.setattr(pix_service.efi_client, "send_pix", lambda **kwargs: {"status": "EM_PROCESSAMENTO"})

    def _raise(id_envio):
        raise pix_service.EfiApiError(500, "efi is down")

    monkeypatch.setattr(pix_service.efi_client, "get_send_status", _raise)

    response = client.get(
        "/admin/smoke-test/pix?force_reconcile=true", headers={ADMIN_HEADER: "the-real-token"}
    )
    assert response.status_code == 200
    body = response.json()

    assert body["overall"] == "ok"
    steps = body["steps"]
    assert steps["pix_reconcile"]["ok"] is True
    assert steps["pix_reconcile"]["status_before"] == "processing"
    assert steps["pix_reconcile"]["status_after"] == "processing"


def test_smoke_test_surfaces_efi_failure_reason(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")

    def _raise(**kwargs):
        raise pix_service.EfiApiError(422, "chave Pix do favorecido nao encontrada")

    monkeypatch.setattr(pix_service.efi_client, "send_pix", _raise)

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()

    # A falha no envio Pix não derruba o smoke test em si (o passo roda sem
    # exceção, só o withdrawal em si fica "failed") -- por isso overall
    # continua "ok", mas o motivo específico da Efí fica visível.
    assert body["overall"] == "ok"
    steps = body["steps"]
    assert steps["pix_withdraw"]["ok"] is True
    assert steps["pix_withdraw"]["status"] == "failed"
    assert steps["pix_withdraw"]["failure_reason"] == "HTTP 422: chave Pix do favorecido nao encontrada"
    assert steps["pix_withdrawals_list"]["final_status"] == "failed"
    assert steps["pix_withdrawals_list"]["final_failure_reason"] == (
        "HTTP 422: chave Pix do favorecido nao encontrada"
    )

    # Os dados de teste não devem sobrar no banco depois da execução.
    db = SessionLocal()
    try:
        user_id = steps["register"]["user_id"]
        assert db.query(User).filter(User.id == user_id).first() is None
    finally:
        db.close()


def test_smoke_test_cleans_up_even_when_a_step_fails(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")

    def _raise(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(admin_smoke_test, "apply_ad_callback", _raise)

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "failed"
    assert body["steps"]["register"]["ok"] is True
    assert body["steps"]["cube"]["ok"] is True
    assert body["steps"]["ads"]["ok"] is False
    assert "mining" not in body["steps"]

    db = SessionLocal()
    try:
        user_id = body["steps"]["register"]["user_id"]
        assert db.query(User).filter(User.id == user_id).first() is None
    finally:
        db.close()
