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
    logger.info("Efi get_send_status response for withdrawal %s: %s", withdrawal.id, result)
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


@celery_app.task(name="pix.reconcile_pending_withdrawals")
def reconcile_pending_withdrawals() -> None:
    """Seção 11, correção v2: webhooks podem chegar fora de ordem, duplicados
    ou nunca chegar. Todo withdrawal parado em "processing" há mais de
    RECONCILE_AFTER_MINUTES consulta o status real na Efí em vez de confiar
    só no webhook."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=RECONCILE_AFTER_MINUTES)
    db = SessionLocal()
    try:
        stuck = (
            db.query(Withdrawal)
            .filter(Withdrawal.status == WithdrawalStatus.PROCESSING, Withdrawal.created_at < cutoff)
            .all()
        )
        for withdrawal in stuck:
            reconcile_withdrawal(db, withdrawal)
    finally:
        db.close()


@celery_app.task(name="reward.update_reward_config")
def update_reward_config() -> None:
    """Roda 1x/dia (ver beat_schedule em app/workers/celery_app.py): busca o
    eCPM médio do dia anterior no bloco de anúncios premiado via AdMob
    Reporting API e atualiza o valor de recompensa por sessão vigente
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
