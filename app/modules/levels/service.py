from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.models.user import User

# 1 XP por R$0,01 ganho em coletas de mineração (decisão confirmada com o
# usuário) -- lido do reward_amount FINAL já creditado (depois de Cubo
# Épico/multiplicador de missão semanal, ver app/modules/mining/service.py e
# app/modules/missions/service.py), então bônus empilhados na coleta já
# rendem mais XP automaticamente, sem nenhuma lógica de bônus própria aqui.
XP_PER_REAL = Decimal("100")

# XP bônus fixo ao completar a missão semanal (decisão confirmada com o
# usuário) -- ver User.weekly_missions_completed/maybe_activate_weekly_mission
# em app/modules/missions/service.py.
WEEKLY_MISSION_XP_BONUS = 100

# Curva de nível (decisão confirmada com o usuário): custo pra sair do
# nível N pro N+1 cresce linearmente (150, 225, 300, ...), o que faz o
# XP TOTAL acumulado crescer de forma quadrática -- curva progressiva
# clássica de RPG, níveis iniciais saem relativamente rápido, níveis altos
# vão exigindo cada vez mais. Subir de nível é só status/visual (seção
# "Níveis") -- nenhum multiplicador ou vantagem mecânica depende disto.
LEVEL_XP_BASE = 150
LEVEL_XP_STEP = 75


@dataclass
class LevelStatus:
    level: int
    xp: int
    xp_into_level: int
    xp_for_next_level: int


def xp_to_next_level(level: int) -> int:
    """XP necessário pra sair de `level` pra `level + 1`."""
    return LEVEL_XP_BASE + LEVEL_XP_STEP * (level - 1)


def cumulative_xp_for_level(level: int) -> int:
    """XP total necessário pra ALCANÇAR `level` (nível 1 = 0 XP, todo mundo
    começa nele) -- forma fechada da soma de xp_to_next_level(1..level-1):
    sum_{n=1}^{level-1} (LEVEL_XP_BASE + LEVEL_XP_STEP*(n-1))
    = LEVEL_XP_STEP/2 * (level-1) * level + (LEVEL_XP_BASE - LEVEL_XP_STEP) * (level-1)."""
    n = level - 1
    return (LEVEL_XP_STEP * n * (n + 1)) // 2 + (LEVEL_XP_BASE - LEVEL_XP_STEP) * n


def level_from_xp(xp: int) -> LevelStatus:
    """Maior nível cujo cumulative_xp_for_level ainda cabe em `xp`. Loop
    simples (não a fórmula quadrática invertida) de propósito -- xp de
    produção nunca chega perto de exigir mais que algumas centenas de
    iterações (curva quadrática: dobrar o nível custa ~4x mais XP), e o
    loop deixa a lógica óbvia de auditar/testar, sem risco de erro de
    arredondamento de ponto flutuante na inversão da fórmula."""
    level = 1
    while cumulative_xp_for_level(level + 1) <= xp:
        level += 1
    xp_into_level = xp - cumulative_xp_for_level(level)
    return LevelStatus(
        level=level,
        xp=xp,
        xp_into_level=xp_into_level,
        xp_for_next_level=xp_to_next_level(level),
    )


def xp_from_reward_total(lifetime_reward_total: Decimal) -> int:
    """XP ganho minerando, derivado do total histórico de LedgerEntry
    `reward` (mesma métrica que _lifetime_totals já calcula pro ranking
    geral, ver app/modules/ranking/service.py) -- nunca persistido à parte,
    sempre um múltiplo exato de XP_PER_REAL já que todo reward_amount é
    quantizado em centavos."""
    return int(lifetime_reward_total * XP_PER_REAL)


def total_xp(lifetime_reward_total: Decimal, weekly_missions_completed: int) -> int:
    return xp_from_reward_total(lifetime_reward_total) + weekly_missions_completed * WEEKLY_MISSION_XP_BONUS


def _lifetime_reward_total(db: Session, user_id: int) -> Decimal:
    return Decimal(
        db.query(func.coalesce(func.sum(LedgerEntry.amount), 0))
        .filter(LedgerEntry.user_id == user_id, LedgerEntry.type == LedgerEntryType.REWARD)
        .scalar()
    )


def get_level_status(db: Session, user: User) -> LevelStatus:
    lifetime_reward_total = _lifetime_reward_total(db, user.id)
    xp = total_xp(lifetime_reward_total, user.weekly_missions_completed)
    return level_from_xp(xp)
