from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class MiningStartRequest(BaseModel):
    cube_id: int
    ad_view_id: int


class MiningSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    cube_id: int
    ad_view_id: int
    started_at: datetime
    ends_at: datetime
    status: str
    epic_bonus_applied: bool
    # 0, 1 ou 2 -- quantos dos EPIC_BONUS_VIDEOS_REQUIRED vídeos do Cubo
    # Épico já foram assistidos (ver MiningSession.epic_bonus_videos_watched
    # em app/models/mining_session.py). epic_bonus_applied só vira true
    # quando este campo chega em 2.
    epic_bonus_videos_watched: int
    speedup_used: bool


class MiningStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    ends_at: datetime
    ready_to_collect: bool


class MiningCollectRequest(BaseModel):
    session_id: int


class MiningCollectResponse(BaseModel):
    session_id: int
    status: str
    reward_amount: Decimal


class MiningEpicBonusRequest(BaseModel):
    session_id: int
    ad_view_id: int


class MiningSpeedupRequest(BaseModel):
    session_id: int
    ad_view_id: int
