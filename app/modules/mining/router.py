import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.mining import service
from app.schemas.mining import (
    MiningCollectRequest,
    MiningCollectResponse,
    MiningSessionRead,
    MiningStartRequest,
    MiningStatusRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mining", tags=["mining"])


@router.post("/start", response_model=MiningSessionRead, status_code=status.HTTP_201_CREATED)
def start(
    payload: MiningStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        session = service.start_mining_session(db, current_user.id, payload.cube_id, payload.ad_view_id)
    except service.CubeNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cube not found")
    except service.AdViewNotConfirmedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ad_view is not confirmed")
    except service.AdViewAlreadyUsedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ad_view already used to start a mining session")
    return session


@router.get("/status", response_model=MiningStatusRead)
def get_status(
    session_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.get_mining_status(db, current_user.id, session_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mining session not found")
    return result


@router.post("/collect", response_model=MiningCollectResponse)
def collect(
    payload: MiningCollectRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.info(
        "mining collect request session_id=%s idempotency_key=%s", payload.session_id, idempotency_key
    )
    try:
        session, reward_amount = service.collect_mining_session(db, current_user.id, payload.session_id)
    except service.SessionNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mining session not found")
    except service.SessionNotReadyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "mining session is not ready to collect")
    except service.InsufficientRewardFundError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "reward fund unavailable, try again later")
    return MiningCollectResponse(session_id=session.id, status=session.status, reward_amount=reward_amount)
