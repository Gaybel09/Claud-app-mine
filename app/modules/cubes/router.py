from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.cube import Cube
from app.models.user import User
from app.schemas.cube import CubeRead

router = APIRouter(prefix="/cubes", tags=["cubes"])


@router.get("/me", response_model=list[CubeRead])
def list_my_cubes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Cube)
        .filter(Cube.user_id == current_user.id)
        .order_by(Cube.acquired_at.asc())
        .all()
    )
