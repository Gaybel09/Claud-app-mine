"""Cliente HTTP para o Pix Out da Efí (seção 11).

Baseado na documentação pública da Efí (dev.efipay.com.br/docs/api-pix):
- Autenticação OAuth2 client_credentials em POST /oauth/token, com Basic
  Auth (client_id/client_secret) e mTLS (o certificado da conta em toda
  chamada, inclusive na autenticação).
- Envio de Pix: PUT /v3/gn/pix/:idEnvio, onde idEnvio é a nossa própria
  idempotency_key -- a Efí garante que reenviar o mesmo idEnvio nunca
  debita duas vezes.
- Consulta de um envio (usada pela reconciliação): GET
  /v2/gn/pix/enviados/id-envio/:idEnvio.
- Webhook de confirmação: status "REALIZADO" (pago), "NAO_REALIZADO"
  (falhou) ou "EM_PROCESSAMENTO", com o idEnvio em gnExtras.idEnvio.

TODO: este sandbox não tem acesso de rede a efipay.com.br para validar os
payloads exatos contra a API viva -- confira a doc oficial (link acima)
antes de operar em produção, especialmente o corpo de POST /oauth/token e
o formato exato da resposta de envio/consulta.
"""

import base64
import tempfile
from decimal import Decimal

import httpx

from app.core.config import settings

SANDBOX_BASE_URL = "https://pix-h.api.efipay.com.br"
PRODUCTION_BASE_URL = "https://pix.api.efipay.com.br"


class EfiConfigurationError(Exception):
    pass


class EfiApiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Efi API error {status_code}: {message}")


def _resolve_certificate_path() -> str:
    if settings.EFI_CERTIFICATE_BASE64:
        cert_bytes = base64.b64decode(settings.EFI_CERTIFICATE_BASE64)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        tmp.write(cert_bytes)
        tmp.flush()
        tmp.close()
        return tmp.name
    if settings.EFI_CERTIFICATE_PATH:
        return settings.EFI_CERTIFICATE_PATH
    raise EfiConfigurationError(
        "Efi certificate not configured -- set EFI_CERTIFICATE_PATH or EFI_CERTIFICATE_BASE64"
    )


class EfiPixClient:
    def __init__(self) -> None:
        self._access_token: str | None = None

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE_URL if settings.EFI_SANDBOX else PRODUCTION_BASE_URL

    def _http_client(self) -> httpx.Client:
        if not settings.EFI_CLIENT_ID or not settings.EFI_CLIENT_SECRET:
            raise EfiConfigurationError("EFI_CLIENT_ID/EFI_CLIENT_SECRET not configured")
        cert_path = _resolve_certificate_path()
        return httpx.Client(base_url=self.base_url, cert=cert_path, timeout=30.0)

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        with self._http_client() as client:
            response = client.post(
                "/oauth/token",
                auth=(settings.EFI_CLIENT_ID, settings.EFI_CLIENT_SECRET),
                json={"grant_type": "client_credentials"},
            )
        if response.status_code != 200:
            raise EfiApiError(response.status_code, response.text)
        self._access_token = response.json()["access_token"]
        return self._access_token

    def send_pix(self, *, id_envio: str, amount: Decimal, favorecido_chave: str) -> dict:
        """Dispara o envio (Pix Out) para a chave `favorecido_chave`.
        `id_envio` é a nossa idempotency_key -- reenviar o mesmo id_envio
        nunca duplica o pagamento, por garantia da própria Efí."""
        if not settings.EFI_PAYER_PIX_KEY:
            raise EfiConfigurationError("EFI_PAYER_PIX_KEY not configured")

        token = self._get_access_token()
        body = {
            "valor": f"{amount:.2f}",
            "pagador": {"chave": settings.EFI_PAYER_PIX_KEY},
            "favorecido": {"chave": favorecido_chave},
        }
        with self._http_client() as client:
            response = client.put(
                f"/v3/gn/pix/{id_envio}",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
        if response.status_code not in (200, 201):
            raise EfiApiError(response.status_code, response.text)
        return response.json()

    def get_send_status(self, id_envio: str) -> dict:
        """Consulta o status real de um envio -- usada pelo worker de
        reconciliação (seção 11, correção v2), não só pelo webhook."""
        token = self._get_access_token()
        with self._http_client() as client:
            response = client.get(
                f"/v2/gn/pix/enviados/id-envio/{id_envio}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code != 200:
            raise EfiApiError(response.status_code, response.text)
        return response.json()


efi_client = EfiPixClient()
