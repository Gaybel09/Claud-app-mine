from fastapi import FastAPI

from app.core.config import settings
from app.modules.health.router import router as health_router

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(health_router)
