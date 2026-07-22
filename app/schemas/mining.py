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
