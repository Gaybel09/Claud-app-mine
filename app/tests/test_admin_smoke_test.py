from decimal import Decimal

from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.modules.admin import smoke_test as admin_smoke_test
from app.modules.pix import service as pix_service

ADMIN_HEADER = "X-Admin-Token"


def test_smoke_test_returns_404_when_not_configured(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", None)

    response = client.get("/admin/smoke-test/pix", headers={ADMIN_HEADER: "anything"})
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
    assert steps["pix_withdrawals_list"]["ok"] is True
    assert steps["pix_withdrawals_list"]["final_status"] == "processing"

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
