from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AdWatchRequest(BaseModel):
    ad_network: str


class AdCallbackRequest(BaseModel):
    ad_view_id: int
    # Simula o parâmetro `user_id` que redes reais de SSV (ex: AdMob) devolvem
    # no callback, setado pelo app ao pedir o anúncio. Usado para conferir que
    # o callback corresponde ao ad_view certo antes de confirmar.
    user_id: int
    status: Literal["confirmed", "rejected"]


class AdViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    ad_network: str
    watched_at: datetime
    status: str
