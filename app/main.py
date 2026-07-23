from fastapi import FastAPI

from app.core.config import settings
from app.modules.ads.router import router as ads_router
from app.modules.auth.router import router as auth_router
from app.modules.cubes.router import router as cubes_router
from app.modules.health.router import router as health_router
from app.modules.mining.router import router as mining_router
from app.modules.pix.router import router as pix_router
from app.modules.wallet.router import router as wallet_router

app = FastAPI(title=settings.PROJECT_NAME)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(wallet_router)
app.include_router(ads_router)
app.include_router(mining_router)
app.include_router(cubes_router)
app.include_router(pix_router)
