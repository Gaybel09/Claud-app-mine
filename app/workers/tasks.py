import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="mining.send_ready_notification")
def send_mining_ready_notification(mining_session_id: int) -> None:
    """Dispara o lembrete de "cubo pronto" agendado para ends_at (seção 7,
    passo 4). Só notifica -- nunca escreve em mining_sessions.status, que
    continua sendo calculado on-the-fly (correção v2 da seção 5)."""
    # TODO: plugar Firebase Cloud Messaging aqui (seção 2) quando a
    # integração de push estiver configurada. Por ora só loga.
    logger.info("mining session %s is ready to collect", mining_session_id)
