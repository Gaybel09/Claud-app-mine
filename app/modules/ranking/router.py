from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.ranking.service import get_ranking
from app.schemas.ranking import RankingRead

router = APIRouter(prefix="/ranking", tags=["ranking"])


@router.get("", response_model=RankingRead)
def ranking(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Top 10 geral (acumulado, nunca reseta) + Top 10 do estado/país do
    usuário (se detectado -- ver User.country_code/state_code), com a
    posição do próprio usuário destacada em cada escopo (ver
    app/modules/ranking/service.py)."""
    return get_ranking(db, current_user)
