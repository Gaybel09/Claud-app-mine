import logging
from functools import lru_cache

import geoip2.database
import geoip2.errors
from fastapi import Request

from app.core.config import settings

logger = logging.getLogger(__name__)

_warned_missing_db = False


def get_client_ip(request: Request) -> str:
    """IP real do cliente, considerando o proxy reverso do Render.

    request.client.host sozinho aponta pro proxy do Render, não pro
    dispositivo do usuário -- por isso preferimos o primeiro IP de
    X-Forwarded-For (o mais próximo do cliente original na cadeia), com
    request.client.host como fallback (ex: testes locais sem proxy)."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


@lru_cache(maxsize=1)
def _get_reader() -> "geoip2.database.Reader | None":
    """Carrega o banco GeoLite2-City local uma única vez por processo.

    Sem custo por requisição e sem limite de taxa -- ao contrário de uma
    API HTTP de terceiro -- mas depende do arquivo .mmdb já estar no disco
    (ver GEOIP_DB_PATH em app/core/config.py e
    scripts/download_geoip_db.py). Se o arquivo não existir ainda (ex:
    ambiente novo antes de configurar a licença MaxMind), degrada de forma
    graciosa: country_code/state_code ficam None em vez de derrubar a
    aplicação."""
    global _warned_missing_db
    if not settings.GEOIP_DB_PATH:
        return None
    try:
        return geoip2.database.Reader(settings.GEOIP_DB_PATH)
    except (FileNotFoundError, OSError):
        if not _warned_missing_db:
            logger.warning(
                "GeoLite2 database not found at %s -- country/state detection "
                "disabled until it's downloaded (see scripts/download_geoip_db.py)",
                settings.GEOIP_DB_PATH,
            )
            _warned_missing_db = True
        return None


def lookup_country_state(ip_address: str) -> tuple[str | None, str | None]:
    """(country_code, state_code) a partir do IP, via GeoLite2-City local.

    state_code é o código ISO 3166-2 da subdivisão mais específica (ex:
    "SP" para São Paulo) quando o banco reconhece uma -- None para IPs de
    países sem subdivisão mapeada, endereços privados/reservados (ex:
    testes locais), ou quando o banco não está disponível."""
    reader = _get_reader()
    if reader is None:
        return None, None
    try:
        response = reader.city(ip_address)
    except (geoip2.errors.AddressNotFoundError, ValueError):
        return None, None
    return response.country.iso_code, response.subdivisions.most_specific.iso_code
