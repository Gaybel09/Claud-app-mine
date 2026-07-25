from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RewardConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value_per_session: Decimal
    avg_ecpm: Decimal | None
    updated_at: datetime
