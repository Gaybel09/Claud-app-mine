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
import hashlib
import tempfile
from decimal import Decimal

import httpx

from app.core.config import settings

SANDBOX_BASE_URL = "https://pix-h.api.efipay.com.br"
PRODUCTION_BASE_URL = "https://pix.api.efipay.com.br"

# A Efí exige idEnvio casando com ^[a-zA-Z0-9]{1,35}$ -- só alfanumérico,
# sem hífen. Nossa idempotency_key normalmente é um UUID (com hífens) ou
# qualquer string escolhida pelo chamador, então nunca passa direto.
ID_ENVIO_LENGTH = 32


def derive_id_envio(source: str) -> str:
    """Deriva um idEnvio alfanumérico válido para a Efí a partir de um
    identificador arbitrário (nossa idempotency_key). Determinístico -- o
    mesmo `source` sempre gera o mesmo id_envio, preservando a garantia real
    de idempotência da Efí (reenviar o mesmo idEnvio nunca duplica o
    pagamento) mesmo com uma idempotency_key que não seja alfanumérica."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:ID_ENVIO_LENGTH]


class EfiConfigurationError(Exception):
    pass


class EfiApiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Efi API error {status_code}: {message}")


_cached_certificate_path: str | None = None


def _write_temp_pem(content: bytes) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    tmp.write(content)
    tmp.flush()
    tmp.close()
    return tmp.name


def _resolve_certificate_path() -> str:
    """Resolve o caminho do certificado mTLS, priorizando as formas
    "inline" (sem precisar de um arquivo já montado em disco) sobre o
    caminho de arquivo puro:

    1. EFI_CERTIFICATE_PEM -- o PEM combinado (certificado + chave, sem
       senha) como texto puro, colado direto na variável de ambiente.
    2. EFI_CERTIFICATE_BASE64 -- o mesmo tipo de conteúdo, mas em base64
       (útil quando o mecanismo de env vars não aceita texto multilinha
       de forma confiável).
    3. EFI_CERTIFICATE_PATH -- caminho de um arquivo já existente no disco
       (ex: um Secret File montado).

    Para as duas primeiras, o conteúdo é escrito uma única vez num arquivo
    temporário na primeira chamada (não em cada requisição) e o caminho
    fica cacheado no processo -- não há necessidade de um hook de
    startup separado em main.py para isso.
    """
    global _cached_certificate_path
    if _cached_certificate_path:
        return _cached_certificate_path

    if settings.EFI_CERTIFICATE_PEM:
        _cached_certificate_path = _write_temp_pem(settings.EFI_CERTIFICATE_PEM.encode("utf-8"))
    elif settings.EFI_CERTIFICATE_BASE64:
        _cached_certificate_path = _write_temp_pem(base64.b64decode(settings.EFI_CERTIFICATE_BASE64))
    elif settings.EFI_CERTIFICATE_PATH:
        _cached_certificate_path = settings.EFI_CERTIFICATE_PATH
    else:
        raise EfiConfigurationError(
            "Efi certificate not configured -- set EFI_CERTIFICATE_PEM, "
            "EFI_CERTIFICATE_BASE64, or EFI_CERTIFICATE_PATH"
        )
    return _cached_certificate_path


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

    def _request_new_access_token(self):
        """Faz a chamada POST /oauth/token de verdade -- sem checar nem
        popular o cache. Base compartilhada por _get_access_token,
        check_auth e _get_fresh_access_token."""
        with self._http_client() as client:
            return client.post(
                "/oauth/token",
                auth=(settings.EFI_CLIENT_ID, settings.EFI_CLIENT_SECRET),
                json={"grant_type": "client_credentials"},
            )

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        response = self._request_new_access_token()
        if response.status_code != 200:
            raise EfiApiError(response.status_code, response.text)
        self._access_token = response.json()["access_token"]
        return self._access_token

    def _get_fresh_access_token(self) -> str:
        """Como _get_access_token, mas sempre pede um token novo à Efí,
        ignorando qualquer token cacheado -- necessário porque mudar os
        escopos de uma aplicação no painel da Efí (ex: adicionar "Alterar
        Webhooks") não invalida tokens já emitidos: um token cacheado de
        uma chamada anterior no mesmo processo continuaria com os escopos
        antigos, e a Efí rejeitaria a chamada com insufficient_scope mesmo
        depois do escopo ter sido adicionado. Também atualiza o cache com o
        token novo, para chamadas seguintes no mesmo processo já saírem
        com os escopos atuais."""
        response = self._request_new_access_token()
        if response.status_code != 200:
            raise EfiApiError(response.status_code, response.text)
        self._access_token = response.json()["access_token"]
        return self._access_token

    def check_auth(self) -> None:
        """Autentica de verdade contra a Efí, ignorando qualquer token
        cacheado -- usado só para diagnóstico (GET /pix/health), pra
        confirmar client_id/secret/certificado numa chamada real, não
        reaproveitar um token de uma verificação anterior.

        Não retorna nem loga o token; levanta EfiConfigurationError ou
        EfiApiError em caso de falha, sem incluir o corpo cru da resposta
        da Efí na mensagem (quem chama isso é um endpoint público)."""
        response = self._request_new_access_token()
        if response.status_code != 200:
            raise EfiApiError(response.status_code, "authentication failed")
        if "access_token" not in response.json():
            raise EfiApiError(response.status_code, "unexpected response shape")

    def send_pix(self, *, id_envio: str, amount: Decimal, favorecido_chave: str) -> dict:
        """Dispara o envio (Pix Out) para a chave `favorecido_chave`.
        `id_envio` precisa já estar no formato exigido pela Efí (alfanumérico,
        até 35 caracteres -- ver derive_id_envio) -- reenviar o mesmo
        id_envio nunca duplica o pagamento, por garantia da própria Efí."""
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

    def register_webhook(self, *, pix_key: str, webhook_url: str) -> dict:
        """Registra a URL de webhook para uma chave Pix -- PUT
        /v2/webhook/:chave. Só precisa ser feito uma vez por chave (ou de
        novo se a URL mudar); depois disso a Efí passa a chamar
        `webhook_url` para confirmar envios feitos com essa chave como
        pagadora. Usado por GET /admin/register-efi-webhook (diagnóstico).

        Sempre pede um token novo (_get_fresh_access_token), nunca reaproveita
        um token cacheado -- necessário para o token refletir escopos
        adicionados recentemente na aplicação Efí (ver
        _get_fresh_access_token)."""
        token = self._get_fresh_access_token()
        with self._http_client() as client:
            response = client.put(
                f"/v2/webhook/{pix_key}",
                headers={"Authorization": f"Bearer {token}"},
                json={"webhookUrl": webhook_url},
            )
        if response.status_code not in (200, 201):
            raise EfiApiError(response.status_code, response.text)
        return response.json()


efi_client = EfiPixClient()
