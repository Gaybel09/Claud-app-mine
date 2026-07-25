"""Rate limiting (seção 11, antifraude básico) via slowapi/limits.

Storage no mesmo Redis já usado pelo resto do backend (REDIS_URL) -- em
memória local não funcionaria direito com mais de uma instância do serviço
web rodando ao mesmo tempo (cada instância teria seu próprio contador). O
prefixo de chave ("ratelimit") é só pra `limiter.reset()` (usado nos testes,
ver conftest.py) limpar só as chaves do rate limit, sem mexer em nada mais
que divida o mesmo Redis (ex: cache de saldo, fila do Celery).

Cada rota sensível aplica DOIS limites (dois decorators @limiter.limit(...)
empilhados):
  1. por IP (get_remote_address) -- pega abuso de várias contas vindo de um
     único IP/rede.
  2. por credencial (get_auth_token_key) -- pega abuso de uma única conta/
     token vindo de IPs diferentes (ex: troca de IP/proxy).
Nenhum dos dois sozinho cobre os dois cenários.

O check do rate limit roda dentro do corpo da própria função decorada, que
o FastAPI só chama DEPOIS de resolver as dependências da rota (Depends) com
sucesso -- então uma requisição rejeitada por auth (401, token ausente/
inválido) nunca chega a incrementar nenhum contador. Isso é intencional: um
401 já é barato de rejeitar (não bate no banco), o alvo real desses limites
é tráfego que passa da autenticação -- uma conta (ou token roubado/válido)
sendo usada em volume alto.
"""

import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def get_auth_token_key(request: Request) -> str:
    """Chave por credencial autenticada -- sem decodificar/verificar o
    token de novo (isso já acontece nas dependências de auth do próprio
    endpoint, ex: get_current_user); só um hash do Bearer token cru, pra
    nunca guardar token em claro na chave do rate limit. Requisições sem
    token caem todas no mesmo bucket "anonymous" -- esse limite sozinho não
    protege quem nunca manda token, quem cobre esse caso é o limite por IP
    (get_remote_address)."""
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return "anonymous"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    key_prefix="ratelimit",
)

# Cadastro deveria acontecer uma vez por dispositivo de verdade; alguns
# retries por falha de rede/reinstalação são esperados, mas nada perto de
# um volume alto -- o alvo é bloquear scripts de criação em massa de
# contas (o vetor de abuso mais direto: cada cadastro gera cubo inicial e
# passa a poder sacar do fundo de recompensas).
REGISTER_LIMIT_PER_IP = "5/hour"
REGISTER_LIMIT_PER_TOKEN = "5/hour"

# Login é chamado a cada abertura do app / refresh de token -- precisa de
# folga generosa pro uso normal (inclusive várias contas atrás do mesmo
# IP/NAT), mas ainda limitado o bastante pra travar enumeração agressiva.
LOGIN_LIMIT_PER_IP = "30/minute"
LOGIN_LIMIT_PER_TOKEN = "20/minute"

# Assistir um anúncio de verdade leva tempo; 20/min (1 a cada 3s) já é
# folgado pro uso humano normal, mas trava scripts tentando gerar ad_views
# em volume pra depois abusar do fluxo de mineração.
ADS_WATCH_LIMIT_PER_IP = "60/minute"
ADS_WATCH_LIMIT_PER_TOKEN = "20/minute"

# Coletar deveria acontecer ~1x por ciclo de mineração (2h); alguns
# cliques de "tá pronto?" perto da hora são esperados, mas nada que
# precise de mais de 10/min -- o alvo é limitar spam de polling/tentativas
# de abusar do lock de linha e da idempotência.
MINING_COLLECT_LIMIT_PER_IP = "30/minute"
MINING_COLLECT_LIMIT_PER_TOKEN = "10/minute"

# Operação financeira -- o mais sensível dos cinco. Um saque legítimo é
# esporádico, não repetido; o alvo é travar tanto uma conta comprometida
# tentando vários saques quanto um IP hospedando várias contas abusivas.
PIX_WITHDRAW_LIMIT_PER_IP = "10/hour"
PIX_WITHDRAW_LIMIT_PER_TOKEN = "5/hour"
