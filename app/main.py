from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.rate_limit import limiter
from app.modules.admin.router import router as admin_router
from app.modules.admin_panel.router import router as admin_panel_router
from app.modules.ads.router import router as ads_router
from app.modules.auth.router import router as auth_router
from app.modules.cubes.router import router as cubes_router
from app.modules.health.router import router as health_router
from app.modules.mining.router import router as mining_router
from app.modules.pix.router import router as pix_router
from app.modules.wallet.router import router as wallet_router

app = FastAPI(title=settings.PROJECT_NAME)

# Seção 11 (antifraude): rate limiting por IP e por credencial nas rotas
# mais sensíveis a abuso -- ver app/core/rate_limit.py para os limites
# escolhidos e o porquê de cada um.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(wallet_router)
app.include_router(ads_router)
app.include_router(mining_router)
app.include_router(cubes_router)
app.include_router(pix_router)
app.include_router(admin_router)
app.include_router(admin_panel_router)
