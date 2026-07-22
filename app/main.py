from fastapi import FastAPI

from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.wallet.router import router as wallet_router

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(wallet_router)
