"""Cliente da AdMob Reporting API (seção 7) -- usado só para ler o eCPM
médio diário do bloco de anúncios premiado, para calcular o valor de
recompensa por sessão (ver app/modules/reward/service.py).

Baseado na documentação pública do Google (developers.google.com/admob/api):
- Autenticação OAuth2 "refresh_token" grant em POST
  https://oauth2.googleapis.com/token, com as credenciais de um OAuth client
  do Google Cloud (mesmo projeto/conta vinculado ao AdMob) -- não é
  client_credentials (a AdMob API não aceita conta de serviço pura; precisa
  de um refresh_token obtido uma vez via consentimento OAuth de um usuário
  com acesso à conta AdMob).
- Relatório de rede: POST
  https://admob.googleapis.com/v1/accounts/{publisherId}/networkReport:generate,
  filtrado por dimensão AD_UNIT e métrica IMPRESSION_RPM (valor monetário em
  "micros" -- 1_000_000 micros = 1 unidade da moeda da conta). NÃO existe
  métrica "OBSERVED_ECPM" na AdMob Reporting API v1 -- IMPRESSION_RPM é a
  correta para eCPM (a API chama de "RPM", mas é o mesmo valor: receita
  estimada por 1000 impressões).

TODO: este sandbox não tem acesso de rede a googleapis.com para validar os
payloads exatos contra a API viva (mesma limitação já registrada em
app/core/efi.py para a Efí) -- confira a documentação oficial acima antes de
operar em produção, especialmente o formato exato de networkReport:generate.
"""

from datetime import date
from decimal import Decimal

import httpx

from app.core.config import settings

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
REPORTING_BASE_URL = "https://admob.googleapis.com/v1"

MICROS_PER_UNIT = Decimal("1000000")


class AdMobConfigurationError(Exception):
    pass


class AdMobApiError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"AdMob API error {status_code}: {message}")


class AdMobReportingClient:
    def _require_credentials(self) -> None:
        if not (
            settings.ADMOB_CLIENT_ID
            and settings.ADMOB_CLIENT_SECRET
            and settings.ADMOB_REFRESH_TOKEN
            and settings.ADMOB_PUBLISHER_ID
        ):
            raise AdMobConfigurationError(
                "ADMOB_CLIENT_ID/ADMOB_CLIENT_SECRET/ADMOB_REFRESH_TOKEN/"
                "ADMOB_PUBLISHER_ID not configured"
            )

    def _get_access_token(self) -> str:
        """Sempre pede um access_token novo via refresh_token -- roda no
        máximo 1x/dia (worker diário), então não vale a pena cachear um
        token que expira em ~1h entre execuções."""
        self._require_credentials()
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                OAUTH_TOKEN_URL,
                data={
                    "client_id": settings.ADMOB_CLIENT_ID,
                    "client_secret": settings.ADMOB_CLIENT_SECRET,
                    "refresh_token": settings.ADMOB_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
            )
        if response.status_code != 200:
            raise AdMobApiError(response.status_code, response.text)
        return response.json()["access_token"]

    def get_average_ecpm(self, target_date: date, ad_unit_id: str | None = None) -> Decimal | None:
        """eCPM médio do bloco de anúncios em `target_date` (métrica
        IMPRESSION_RPM da AdMob Reporting API -- não existe "OBSERVED_ECPM"
        na v1; IMPRESSION_RPM é o nome correto para essa métrica, mesmo
        conceito de eCPM), na moeda da própria conta AdMob -- NÃO convertido
        para BRL (isso é responsabilidade de quem chama, ver
        app/modules/reward/service.py e settings.ADMOB_USD_TO_BRL_RATE).
        Retorna None se não houver nenhuma linha para o dia (ex: bloco sem
        nenhuma impressão) -- quem chama decide o que fazer nesse caso (ver
        app/modules/reward/service.py, que mantém o valor vigente inalterado)."""
        ad_unit_id = ad_unit_id or settings.ADMOB_AD_UNIT_ID
        token = self._get_access_token()

        report_date = {"year": target_date.year, "month": target_date.month, "day": target_date.day}
        body = {
            "reportSpec": {
                "dateRange": {"startDate": report_date, "endDate": report_date},
                "dimensions": ["AD_UNIT"],
                "metrics": ["IMPRESSION_RPM", "IMPRESSIONS"],
                "dimensionFilters": [
                    {"dimension": "AD_UNIT", "matchesAny": {"values": [ad_unit_id]}}
                ],
            }
        }
        with httpx.Client(base_url=REPORTING_BASE_URL, timeout=30.0) as client:
            response = client.post(
                f"/accounts/{settings.ADMOB_PUBLISHER_ID}/networkReport:generate",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
        if response.status_code != 200:
            raise AdMobApiError(response.status_code, response.text)

        for item in response.json():
            row = item.get("row")
            if not row:
                continue
            ecpm_micros = row.get("metricValues", {}).get("IMPRESSION_RPM", {}).get("microsValue")
            if ecpm_micros is not None:
                return Decimal(ecpm_micros) / MICROS_PER_UNIT
        return None


admob_client = AdMobReportingClient()
