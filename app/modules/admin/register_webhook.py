"""Registra o webhook de envio de Pix na Efí para EFI_PAYER_PIX_KEY,
apontando para PUBLIC_BASE_URL + "/pix/webhook" (PUT /v2/webhook/:chave) --
diagnóstico manual, seção 11.

ATENÇÃO -- isto é só para diagnóstico manual, nunca para produção de
verdade (fora de sandbox):
  - Faz uma chamada real de escrita na conta Efí: registra (ou sobrescreve)
    a URL de webhook associada a EFI_PAYER_PIX_KEY.
  - O endpoint GET /admin/register-efi-webhook que chama isto só deve ficar
    acessível enquanto ADMIN_SMOKE_TEST_TOKEN estiver configurado. REMOVA a
    rota (ou pare de configurar essa variável) antes de operar fora de
    sandbox.
"""

from app.core.config import settings
from app.core.efi import EfiApiError, EfiConfigurationError, efi_client


def run_register_efi_webhook() -> dict:
    if not settings.EFI_PAYER_PIX_KEY:
        return {
            "ok": False,
            "error": "EFI_PAYER_PIX_KEY is not configured -- nothing to register",
        }

    webhook_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/pix/webhook"

    try:
        efi_response = efi_client.register_webhook(
            pix_key=settings.EFI_PAYER_PIX_KEY, webhook_url=webhook_url
        )
    except (EfiApiError, EfiConfigurationError) as exc:
        error = f"HTTP {exc.status_code}: {exc.message}" if isinstance(exc, EfiApiError) else str(exc)
        return {
            "ok": False,
            "pix_key": settings.EFI_PAYER_PIX_KEY,
            "webhook_url": webhook_url,
            "error": error,
        }

    return {
        "ok": True,
        "pix_key": settings.EFI_PAYER_PIX_KEY,
        "webhook_url": webhook_url,
        "efi_response": efi_response,
    }
