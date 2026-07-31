from decimal import Decimal

from pydantic import BaseModel


class RankingEntry(BaseModel):
    rank: int
    user_id: int
    display_name: str
    total: Decimal


class ScopeRanking(BaseModel):
    top: list[RankingEntry]
    my_rank: int | None
    my_total: Decimal


class RegionalScopeRanking(ScopeRanking):
    region_code: str
    region_label: str


class RankingRead(BaseModel):
    general: ScopeRanking
    # None quando o usuário ainda não tem país/estado detectado (ex:
    # cadastrado antes desta feature e ainda não fez login de novo) -- ver
    # region_code_for em app/modules/ranking/service.py.
    regional: RegionalScopeRanking | None
