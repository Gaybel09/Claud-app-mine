from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CubeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: str
    speed: Decimal
    bonus_chance: Decimal
    acquired_at: datetime
