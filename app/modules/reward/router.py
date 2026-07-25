from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.reward.service import get_current_reward_config
from app.schemas.reward import RewardConfigRead

router = APIRouter(prefix="/reward", tags=["reward"])


@router.get("/current", response_model=RewardConfigRead)
def current(db: Session = Depends(get_db)):
    """Valor de recompensa por sessão vigente (seção 7), para o app mostrar
    antes de minerar. Público (sem autenticação) -- não expõe nenhum dado
    de usuário, só a configuração global recalculada 1x/dia a partir do
    eCPM médio do AdMob."""
    return get_current_reward_config(db)
