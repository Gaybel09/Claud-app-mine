import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.admob import AdMobApiError, AdMobConfigurationError
from app.core.efi import EfiApiError, EfiConfigurationError, efi_client
from app.db.session import SessionLocal
from app.models.withdrawal import Withdrawal, WithdrawalStatus
from app.modules.pix.service import (
    RECONCILE_AFTER_MINUTES,
    apply_efi_status,
    failure_reason_from_get_status,
)
from app.modules.reward.service import update_reward_config_from_admob
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def reconcile_withdrawal(db: Session, withdrawal: Withdrawal) -> None:
    """Consulta o status real de um saque na Efí e aplica (ver
    apply_efi_status) -- a mesma lógica usada pelo worker periódico
    (reconcile_pending_withdrawals), extraída para poder ser chamada direto
    e na hora, sem esperar o agendamento do Celery Beat nem o corte de
    RECONCILE_AFTER_MINUTES (ex: GET /admin/smoke-test/pix?force_reconcile=true,
    diagnóstico manual). Não levanta em caso de falha ao consultar a Efí --
    só loga, igual ao worker periódico."""
    try:
        result = efi_client.get_send_status(withdrawal.efi_id_envio)
    except (EfiApiError, EfiConfigurationError):
        logger.warning("failed to reconcile withdrawal %s", withdrawal.id, exc_info=True)
        return
    # .info() nunca aparece nos logs -- ver comentário equivalente em
    # admin_reconcile_withdrawal (app/modules/pix/service.py). Este app não
    # configura nível de logging em lugar nenhum, então o root logger fica
    # no default do Python (WARNING) e .info() é descartado antes de
    # chegar em qualquer handler.
    logger.warning("Efi get_send_status response for withdrawal %s: %s", withdrawal.id, result)
    efi_status = result.get("status")
    if efi_status:
        apply_efi_status(
            db,
            id_envio=withdrawal.efi_id_envio,
            efi_status=efi_status,
            failure_reason=failure_reason_from_get_status(result),
        )


@celery_app.task(name="mining.send_ready_notification")
def send_mining_ready_notification(mining_session_id: int) -> None:
    """Dispara o lembrete de "cubo pronto" agendado para ends_at (seção 7,
    passo 4). Só notifica -- nunca escreve em mining_sessions.status, que
    continua sendo calculado on-the-fly (correção v2 da seção 5)."""
    # TODO: plugar Firebase Cloud Messaging aqui (seção 2) quando a
    # integração de push estiver configurada. Por ora só loga.
    logger.info("mining session %s is ready to collect", mining_session_id)


def find_stuck_processing_withdrawals(db: Session) -> list[Withdrawal]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_AFTER_MINUTES)
    return (
        db.query(Withdrawal)
        .filter(Withdrawal.status == WithdrawalStatus.PROCESSING, Withdrawal.created_at < cutoff)
        .all()
    )


def reconcile_stuck_withdrawals(db: Session) -> list[Withdrawal]:
    """Reconcilia todo saque preso em "processing" há mais de
    RECONCILE_AFTER_MINUTES -- lógica compartilhada entre o worker Celery
    periódico (reconcile_pending_withdrawals, abaixo) e o endpoint HTTP de
    reconciliação em lote (POST /admin/withdrawals/reconcile-all, ponte
    gratuita via GitHub Actions enquanto o worker Celery de verdade não
    está aprovado/implantado -- ver render.yaml e README).

    Devolve a lista de withdrawals processados (objetos já atualizados na
    própria sessão, se a Efí confirmou uma mudança de status) -- útil pro
    endpoint HTTP reportar o que aconteceu; o worker periódico ignora o
    retorno."""
    stuck = find_stuck_processing_withdrawals(db)
    for withdrawal in stuck:
        reconcile_withdrawal(db, withdrawal)
    return stuck


@celery_app.task(name="pix.reconcile_pending_withdrawals")
def reconcile_pending_withdrawals() -> None:
    """Seção 11, correção v2: webhooks podem chegar fora de ordem, duplicados
    ou nunca chegar. Todo withdrawal parado em "processing" há mais de
    RECONCILE_AFTER_MINUTES consulta o status real na Efí em vez de confiar
    só no webhook."""
    db = SessionLocal()
    try:
        reconcile_stuck_withdrawals(db)
    finally:
        db.close()


@celery_app.task(name="reward.update_reward_config")
def update_reward_config() -> None:
    """Roda 1x/dia, mas NÃO via celery_app.conf.beat_schedule -- o
    agendamento de verdade é o Cron Job dedicado em render.yaml, que chama
    GET /admin/update-reward-config (mais barato pra uma tarefa diária,
    cobrado só pelos segundos de execução, do que manter esse Background
    Worker rodando 24/7 só por causa dela). Esta task Celery permanece
    definida e chamável (ex: testes, uso manual futuro), só não está no
    beat_schedule pra não duplicar a consulta à AdMob Reporting API todo
    dia. Busca o eCPM médio do dia anterior no bloco de anúncios premiado
    via AdMob Reporting API e atualiza o valor de recompensa por sessão
    vigente
    (seção 7) -- ver app/modules/reward/service.py.

    Não levanta em caso de falha (credenciais da AdMob não configuradas,
    erro de rede/API) -- só loga, igual ao worker de reconciliação de saques
    acima, para uma falha num dia não travar o scheduler nem os dias
    seguintes."""
    db = SessionLocal()
    try:
        update_reward_config_from_admob(db)
    except (AdMobConfigurationError, AdMobApiError):
        logger.warning("failed to update reward_config from AdMob", exc_info=True)
    finally:
        db.close()
