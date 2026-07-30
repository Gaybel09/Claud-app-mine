import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.rate_limit import (
    MINING_COLLECT_LIMIT_PER_IP,
    MINING_COLLECT_LIMIT_PER_TOKEN,
    get_auth_token_key,
    limiter,
)
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.mining import service
from app.schemas.mining import (
    MiningCollectRequest,
    MiningCollectResponse,
    MiningEpicBonusRequest,
    MiningSessionRead,
    MiningSpeedupRequest,
    MiningStartRequest,
    MiningStatusRead,
)

MiningSessionReadOrNone = MiningSessionRead | None

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
    except service.CubeAlreadyMiningError:
        raise HTTPException(status.HTTP_409_CONFLICT, "cube already has an active mining session")
    except service.AdViewNotConfirmedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ad_view is not confirmed")
    except service.AdViewAlreadyUsedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ad_view already used to start a mining session")
    return session


@router.post("/epic-bonus", response_model=MiningSessionRead)
def epic_bonus(
    payload: MiningEpicBonusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cubo Épico -- chamado uma vez POR VÍDEO (2 RewardedAds distintos,
    não 1) enquanto a mineração roda, pra essa sessão pagar
    EPIC_BONUS_MULTIPLIER (1.25x) na coleta assim que o segundo vídeo for
    confirmado. A resposta sempre traz epic_bonus_videos_watched (0/1/2) e
    epic_bonus_applied (só true depois do segundo). Ver docstring completa
    de service.apply_epic_bonus."""
    try:
        session = service.apply_epic_bonus(db, current_user.id, payload.session_id, payload.ad_view_id)
    except service.SessionNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mining session not found")
    except service.SessionNotReadyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "mining session is not running")
    except service.EpicBonusAlreadyUsedError:
        raise HTTPException(status.HTTP_409_CONFLICT, "epic bonus already used for this session")
    except service.AdViewNotConfirmedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ad_view is not confirmed")
    except service.AdViewAlreadyUsedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ad_view already used")
    return session


@router.post("/speedup", response_model=MiningSessionRead)
def speedup(
    payload: MiningSpeedupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Acelerar -- assistir um RewardedAd enquanto a mineração roda para
    reduzir o tempo restante pela metade. Ver docstring completa de
    service.apply_speedup."""
    try:
        session = service.apply_speedup(db, current_user.id, payload.session_id, payload.ad_view_id)
    except service.SessionNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mining session not found")
    except service.SessionNotReadyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "mining session is not running")
    except service.SpeedupAlreadyUsedError:
        raise HTTPException(status.HTTP_409_CONFLICT, "speedup already used for this session")
    except service.NothingToSpeedUpError:
        raise HTTPException(status.HTTP_409_CONFLICT, "mining session is already ready to collect")
    except service.AdViewNotConfirmedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ad_view is not confirmed")
    except service.AdViewAlreadyUsedError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ad_view already used")
    return session


@router.get("/active-session", response_model=MiningSessionReadOrNone)
def active_session(
    cube_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Chamado pelo app ao carregar a tela do cubo, para restaurar o estado
    de uma mineração em andamento -- ver docstring de
    service.get_active_session_for_cube. Devolve `null` (200) quando não há
    sessão RUNNING para este cubo, nunca 404 -- "nenhuma sessão ativa" é um
    resultado válido, não um erro."""
    return service.get_active_session_for_cube(db, current_user.id, cube_id)


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
@limiter.limit(MINING_COLLECT_LIMIT_PER_IP, key_func=get_remote_address)
@limiter.limit(MINING_COLLECT_LIMIT_PER_TOKEN, key_func=get_auth_token_key)
def collect(
    request: Request,
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
