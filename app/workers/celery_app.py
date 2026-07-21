from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "cubemine_pix",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.task_default_queue = "cubemine_pix"
