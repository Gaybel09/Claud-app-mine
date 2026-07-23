from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "cubemine_pix",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.task_default_queue = "cubemine_pix"

# Seção 11, correção v2: reconciliação periódica dos saques Pix presos em
# "processing" -- não depende só do webhook da Efí. Precisa de um processo
# `celery beat` rodando além do worker (não incluído no render.yaml ainda).
celery_app.conf.beat_schedule = {
    "reconcile-pending-withdrawals": {
        "task": "pix.reconcile_pending_withdrawals",
        "schedule": 300.0,  # a cada 5 minutos
    },
}
