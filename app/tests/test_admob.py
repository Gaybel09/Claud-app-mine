from datetime import date
from decimal import Decimal

from app.core import admob
from app.core.admob import AdMobReportingClient


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


class _FakeHttpxClient:
    """Substitui httpx.Client -- captura toda chamada .post() (URL, base_url
    e corpo) para inspecionar exatamente o que o AdMobReportingClient monta,
    sem nenhuma chamada de rede de verdade."""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        self._base_url = kwargs.get("base_url", "")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        _FakeHttpxClient.calls.append({"base_url": self._base_url, "url": url, **kwargs})
        if self._base_url == admob.REPORTING_BASE_URL:
            return _FakeResponse(
                200,
                json_data=[{"row": {"metricValues": {"IMPRESSION_RPM": {"microsValue": "500000"}}}}],
            )
        return _FakeResponse(200, json_data={"access_token": "fake-access-token"})


def _reset_calls():
    _FakeHttpxClient.calls = []


def test_get_average_ecpm_strips_whitespace_from_ad_unit_id_and_publisher_id(monkeypatch):
    """Reproduz o cenário suspeitado: ADMOB_AD_UNIT_ID/ADMOB_PUBLISHER_ID
    colados manualmente no dashboard do Render com espaço/quebra de linha
    grudados -- o valor enviado pro filtro AD_UNIT e pra URL da API precisa
    sair limpo, sem esse lixo, senão a API rejeita como "malformado"."""
    _reset_calls()
    monkeypatch.setattr(admob, "httpx", type("_FakeHttpxModule", (), {"Client": _FakeHttpxClient}))
    monkeypatch.setattr(
        admob.settings, "ADMOB_AD_UNIT_ID", "ca-app-pub-9407999187872272/9926844486.\n"
    )
    monkeypatch.setattr(admob.settings, "ADMOB_PUBLISHER_ID", " pub-9407999187872272 ")
    monkeypatch.setattr(admob.settings, "ADMOB_CLIENT_ID", "client-id")
    monkeypatch.setattr(admob.settings, "ADMOB_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(admob.settings, "ADMOB_REFRESH_TOKEN", "refresh-token")

    client = AdMobReportingClient()
    result = client.get_average_ecpm(date(2026, 7, 24))

    assert result == Decimal("0.5")

    report_call = next(call for call in _FakeHttpxClient.calls if call["base_url"] == admob.REPORTING_BASE_URL)
    assert report_call["url"] == "/accounts/pub-9407999187872272/networkReport:generate"
    filter_values = report_call["json"]["reportSpec"]["dimensionFilters"][0]["matchesAny"]["values"]
    assert filter_values == ["ca-app-pub-9407999187872272/9926844486."]
    # A pontuação (".") não é removida por .strip() -- só espaço/quebra de
    # linha nas pontas. Prova de que o teste captura só o que .strip() de
    # fato resolve, sem prometer mais do que isso.
