from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.levels.service import get_level_status
from app.schemas.levels import LevelStatusRead

router = APIRouter(prefix="/levels", tags=["levels"])


@router.get("/me", response_model=LevelStatusRead)
def my_level(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Nível e progresso de XP do usuário atual (seção "Níveis") -- XP
    ganho minerando é sempre derivado do total histórico de reward no
    ledger, nunca persistido à parte (ver app/modules/levels/service.py).
    Subir de nível é só status/visual, sem nenhuma vantagem mecânica."""
    return get_level_status(db, current_user)
