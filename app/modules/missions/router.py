from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.missions.service import get_weekly_mission_status
from app.schemas.missions import WeeklyMissionRead

router = APIRouter(prefix="/missions", tags=["missions"])


@router.get("/weekly", response_model=WeeklyMissionRead)
def weekly_mission(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Progresso da missão "Minere 10x essa semana" (X/10, reinicia toda
    segunda-feira 00h no horário de Brasília) e o estado do multiplicador
    de recompensa (1.5x por 24h) ganho ao completá-la -- ver
    app/modules/missions/service.py."""
    return get_weekly_mission_status(db, current_user)
