from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.efi import EfiApiError, EfiConfigurationError, efi_client

ADMIN_HEADER = "X-Admin-Token"


def test_register_webhook_returns_404_when_not_configured(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", None)

    response = client.get("/admin/register-efi-webhook", headers={ADMIN_HEADER: "anything"})
    assert response.status_code == 404


def test_register_webhook_rejects_missing_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get("/admin/register-efi-webhook")
    assert response.status_code == 403


def test_register_webhook_rejects_wrong_token(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")

    response = client.get("/admin/register-efi-webhook", headers={ADMIN_HEADER: "wrong-token"})
    assert response.status_code == 403


def test_register_webhook_accepts_query_token_without_header(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", None)

    response = client.get("/admin/register-efi-webhook?token=the-real-token")
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_register_webhook_reports_not_configured_when_no_payer_pix_key(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", None)

    response = client.get("/admin/register-efi-webhook", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "EFI_PAYER_PIX_KEY" in body["error"]


def test_register_webhook_success(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://example-api.onrender.com")

    captured = {}

    def _fake_register(*, pix_key, webhook_url):
        captured["pix_key"] = pix_key
        captured["webhook_url"] = webhook_url
        return {"webhookUrl": webhook_url}

    monkeypatch.setattr(efi_client, "register_webhook", _fake_register)

    response = client.get("/admin/register-efi-webhook", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["pix_key"] == "payer@example.com"
    assert body["webhook_url"] == "https://example-api.onrender.com/pix/webhook"
    assert body["efi_response"] == {"webhookUrl": "https://example-api.onrender.com/pix/webhook"}
    assert captured == {
        "pix_key": "payer@example.com",
        "webhook_url": "https://example-api.onrender.com/pix/webhook",
    }


def test_register_webhook_strips_trailing_slash_from_base_url(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://example-api.onrender.com/")
    monkeypatch.setattr(efi_client, "register_webhook", lambda **kwargs: {})

    response = client.get("/admin/register-efi-webhook", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    assert response.json()["webhook_url"] == "https://example-api.onrender.com/pix/webhook"


def test_register_webhook_surfaces_efi_api_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")

    def _raise(**kwargs):
        raise EfiApiError(400, "invalid webhook url")

    monkeypatch.setattr(efi_client, "register_webhook", _raise)

    response = client.get("/admin/register-efi-webhook", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "HTTP 400: invalid webhook url"


def test_register_webhook_surfaces_configuration_error(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "the-real-token")
    monkeypatch.setattr(settings, "EFI_PAYER_PIX_KEY", "payer@example.com")

    def _raise(**kwargs):
        raise EfiConfigurationError("EFI_CLIENT_ID/EFI_CLIENT_SECRET not configured")

    monkeypatch.setattr(efi_client, "register_webhook", _raise)

    response = client.get("/admin/register-efi-webhook", headers={ADMIN_HEADER: "the-real-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "EFI_CLIENT_ID/EFI_CLIENT_SECRET not configured"
