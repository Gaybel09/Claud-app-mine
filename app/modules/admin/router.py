import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.admob import AdMobApiError, AdMobConfigurationError
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.modules.admin.register_webhook import run_register_efi_webhook
from app.modules.admin.smoke_test import run_pix_smoke_test
from app.modules.mining.service import force_session_ready_for_testing
from app.modules.ranking.service import run_monthly_ranking_payout
from app.modules.reward.service import update_reward_config_from_admob
from app.workers.tasks import reconcile_stuck_withdrawals

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_token(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    token: str | None = Query(None, description="Alternativa ao header X-Admin-Token, para testar via navegador (ex: celular, sem acesso a curl/terminal)."),
) -> None:
    configured_token = settings.ADMIN_SMOKE_TEST_TOKEN
    if not configured_token:
        # Fail closed: sem a variável configurada, a rota se comporta como
        # se não existisse -- nunca fica acessível "por padrão".
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    header_ok = bool(x_admin_token) and secrets.compare_digest(x_admin_token, configured_token)
    query_ok = bool(token) and secrets.compare_digest(token, configured_token)
    if not header_ok and not query_ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid admin token")


def require_diagnostics_enabled() -> None:
    """Segunda camada de proteção, independente do token, só para as rotas
    que são puro diagnóstico de setup (smoke-test/pix, register-efi-webhook)
    -- NÃO aplicada a update-reward-config (chamada de verdade em produção
    pelo Cron Job, ver render.yaml) nem a promote-user/demote-user
    (necessárias em produção real, ver docstring de promote_user).

    Fail closed: mesmo que ADMIN_SMOKE_TEST_TOKEN vaze ou seja adivinhado,
    estas rotas continuam respondendo 404 a menos que
    ENABLE_DIAGNOSTIC_ENDPOINTS esteja explicitamente ligada."""
    if not settings.ENABLE_DIAGNOSTIC_ENDPOINTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.get(
    "/smoke-test/pix",
    dependencies=[Depends(require_diagnostics_enabled), Depends(require_admin_token)],
)
def pix_smoke_test(
    db: Session = Depends(get_db),
    force_reconcile: bool = Query(
        False,
        description=(
            "Roda a reconciliação (mesma lógica do worker periódico "
            "pix.reconcile_pending_withdrawals) logo após o saque, em vez de "
            "esperar o agendamento -- para validar o fluxo sem depender do "
            "webhook."
        ),
    ),
):
    """Diagnóstico manual do fluxo completo (cadastro -> ... -> saque Pix),
    rodando dentro do próprio processo do backend -- ver
    app/modules/admin/smoke_test.py.

    APENAS PARA DIAGNÓSTICO. Cria dados reais (limpos ao final) e dispara
    um envio Pix real na Efí. Fica 404 em produção a menos que
    ENABLE_DIAGNOSTIC_ENDPOINTS esteja explicitamente ligada (além do token
    ADMIN_SMOKE_TEST_TOKEN) -- ligue só temporariamente pelo dashboard do
    Render se precisar, e desligue assim que terminar.
    """
    return run_pix_smoke_test(db, force_reconcile=force_reconcile)


@router.get(
    "/register-efi-webhook",
    dependencies=[Depends(require_diagnostics_enabled), Depends(require_admin_token)],
)
def register_efi_webhook():
    """Registra na Efí a URL de webhook de envio de Pix
    (PUT /v2/webhook/:chave) para EFI_PAYER_PIX_KEY, apontando para
    PUBLIC_BASE_URL + "/pix/webhook" -- ver
    app/modules/admin/register_webhook.py.

    APENAS PARA DIAGNÓSTICO. Faz uma chamada real de escrita na conta Efí
    (registra/sobrescreve a URL de webhook associada à chave). Fica 404 em
    produção a menos que ENABLE_DIAGNOSTIC_ENDPOINTS esteja explicitamente
    ligada (além do token ADMIN_SMOKE_TEST_TOKEN) -- ligue só
    temporariamente pelo dashboard do Render se precisar (ex: reconfigurar
    o webhook porque a URL mudou), e desligue assim que terminar.
    """
    return run_register_efi_webhook()


@router.get(
    "/mining/force-ready",
    dependencies=[Depends(require_diagnostics_enabled), Depends(require_admin_token)],
)
def force_mining_session_ready(session_id: int = Query(...), db: Session = Depends(get_db)):
    """Adianta ends_at de UMA sessão de mineração específica para o
    passado, para testes manuais não precisarem esperar os 30min reais
    (MINING_SESSION_DURATION_SECONDS, app/core/config.py) -- ver docstring
    completa de force_session_ready_for_testing
    (app/modules/mining/service.py). Prefira este endpoint quando bastar
    destravar uma sessão específica: ele não afeta ninguém além da sessão
    indicada, enquanto mudar MINING_SESSION_DURATION_SECONDS direto afeta
    o tempo de mineração de TODO MUNDO em produção.

    APENAS PARA TESTE MANUAL. Fica 404 em produção a menos que
    ENABLE_DIAGNOSTIC_ENDPOINTS esteja explicitamente ligada (além do token
    ADMIN_SMOKE_TEST_TOKEN) -- ligue só temporariamente pelo dashboard do
    Render enquanto estiver testando, e desligue assim que terminar. Não
    altera MINING_SESSION_DURATION_SECONDS nem o status da sessão --
    "pronto para coletar" continua sempre calculado on-the-fly
    (now() >= ends_at).
    """
    session = force_session_ready_for_testing(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mining session not found")
    return {"id": session.id, "status": session.status, "ends_at": session.ends_at.isoformat()}


@router.get("/update-reward-config", dependencies=[Depends(require_admin_token)])
def update_reward_config(db: Session = Depends(get_db)):
    """Roda manualmente a mesma lógica do worker diário
    update_reward_config (ver app/modules/reward/service.py), sem esperar o
    agendamento do Celery Beat (6h) -- útil para validar a integração com a
    AdMob Reporting API sem esperar até o dia seguinte.

    APENAS PARA DIAGNÓSTICO. Escreve de verdade na reward_config (não é
    revertido ao final, ao contrário de /admin/smoke-test/pix) -- é
    exatamente o efeito que o worker teria, só disparado na hora.
    """
    try:
        config = update_reward_config_from_admob(db)
    except AdMobConfigurationError as exc:
        return {"ok": False, "error": str(exc)}
    except AdMobApiError as exc:
        return {"ok": False, "error": exc.message, "status_code": exc.status_code}
    return {
        "ok": True,
        "value_per_session": str(config.value_per_session),
        "avg_ecpm": str(config.avg_ecpm) if config.avg_ecpm is not None else None,
        "updated_at": config.updated_at.isoformat(),
    }


@router.get("/run-monthly-ranking-payout", dependencies=[Depends(require_admin_token)])
def run_monthly_ranking_payout_endpoint(db: Session = Depends(get_db)):
    """Roda manualmente a mesma lógica do job mensal de ranking (seção
    "Ranking", ver app/modules/ranking/service.py), sem esperar o
    agendamento do Cron Job -- útil para validar o cálculo/pagamento do
    Top 10 do mês sem esperar o dia 1.

    APENAS PARA DIAGNÓSTICO... mas escreve de verdade (não é revertido ao
    final, ao contrário de /admin/smoke-test/pix) -- credita bônus reais no
    ledger e debita o reward_fund, exatamente como o Cron Job faria.
    Idempotente por reference_id (ver _credit_ranking_bonus): rodar de novo
    no mesmo mês não paga a mesma posição duas vezes.
    """
    result = run_monthly_ranking_payout(db)
    return {"ok": True, **result}


@router.post("/withdrawals/reconcile-all", dependencies=[Depends(require_admin_token)])
def reconcile_all_withdrawals(db: Session = Depends(get_db)):
    """Reconcilia de uma vez todo saque preso em "processing" há mais de
    RECONCILE_AFTER_MINUTES (app/modules/pix/service.py) -- mesma lógica
    exata do worker Celery periódico (pix.reconcile_pending_withdrawals),
    só disparada via HTTP em vez de esperar o Celery Beat rodar.

    PONTE TEMPORÁRIA: existe para cobrir a lacuna de reconciliação
    automática enquanto o Background Worker de verdade (render.yaml,
    serviço cubemine-pix-reconcile-worker) ainda não foi aprovado/
    implantado (custo mensal recorrente, decisão separada) -- um agendador
    externo gratuito (GitHub Actions cron, ver
    .github/workflows/reconcile-withdrawals.yml e README) chama esta rota
    a cada poucos minutos. Assim que o worker real entrar no ar, esta rota
    (e o workflow) devem ser desativados -- deixá-los ligados não quebra
    nada (reconciliar um saque já resolvido não faz nada, ver
    apply_efi_status), só desperdiça chamadas.

    AO CONTRÁRIO de /admin/smoke-test/pix e /admin/register-efi-webhook,
    não é protegida por ENABLE_DIAGNOSTIC_ENDPOINTS -- precisa continuar
    acessível em produção real enquanto o agendador externo estiver
    chamando (mesmo padrão de /admin/update-reward-config e
    /admin/promote-user). Nunca levanta por falha ao consultar a Efí num
    saque específico -- só loga e segue pro próximo (mesmo comportamento
    do worker periódico), pra um saque com problema não impedir a
    reconciliação dos demais."""
    reconciled = reconcile_stuck_withdrawals(db)
    return {
        "reconciled_count": len(reconciled),
        "withdrawals": [
            {"id": w.id, "status": w.status, "failure_reason": w.failure_reason} for w in reconciled
        ],
    }


@router.post("/promote-user/{user_id}", dependencies=[Depends(require_admin_token)])
def promote_user(user_id: int, db: Session = Depends(get_db)):
    """Dá acesso ao painel admin (is_admin=true) a um usuário -- ver
    GET /admin/users, /admin/withdrawals, /admin/fund (seção 10), que exigem
    login Firebase de um usuário com is_admin=true (não este token).

    Ferramenta de bootstrap manual: ainda não existe nenhum jeito de um
    admin promover outro pelo próprio painel. AO CONTRÁRIO de
    /admin/smoke-test/pix e /admin/register-efi-webhook, esta rota não é
    "só sandbox" -- é a única forma de criar o primeiro admin, e pode
    continuar necessária em produção de verdade até existir um fluxo de
    convite de admin de verdade. Ainda assim, reaproveita a proteção por
    ADMIN_SMOKE_TEST_TOKEN por simplicidade -- avalie separar os tokens se
    for desativar os diagnósticos de sandbox mas precisar manter esta rota.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    user.is_admin = True
    db.commit()
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


@router.post("/demote-user/{user_id}", dependencies=[Depends(require_admin_token)])
def demote_user(user_id: int, db: Session = Depends(get_db)):
    """Reverte promote_user -- remove acesso ao painel admin (is_admin=false)
    de um usuário. Útil para desfazer uma promoção feita por engano."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    user.is_admin = False
    db.commit()
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}
