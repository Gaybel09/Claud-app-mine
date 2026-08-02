from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class WeeklyMissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target: int
    progress: int
    completed: bool
    week_start: datetime
    week_end: datetime
    multiplier: Decimal
    multiplier_active: bool
    # None quando o multiplicador nunca foi ativado (ou já expirou) -- ver
    # WeeklyMissionStatus em app/modules/missions/service.py.
    multiplier_expires_at: datetime | None
