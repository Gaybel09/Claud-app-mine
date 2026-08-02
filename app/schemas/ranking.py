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


class LevelRankingEntry(BaseModel):
    rank: int
    user_id: int
    display_name: str
    level: int
    xp: int


class LevelScopeRanking(BaseModel):
    top: list[LevelRankingEntry]
    my_rank: int | None
    my_level: int
    my_xp: int


class RankingRead(BaseModel):
    general: ScopeRanking
    # None quando o usuário ainda não tem país/estado detectado (ex:
    # cadastrado antes desta feature e ainda não fez login de novo) -- ver
    # region_code_for em app/modules/ranking/service.py.
    regional: RegionalScopeRanking | None
    # Escopo por nível/XP (seção "Níveis") -- separado do total minerado em
    # dinheiro (general/regional acima): um usuário pode estar bem
    # posicionado num e mal no outro (XP inclui o bônus fixo da missão
    # semanal, que não é dinheiro). Nunca None -- todo usuário tem nível
    # (começa no 1 com 0 XP).
    by_level: LevelScopeRanking
