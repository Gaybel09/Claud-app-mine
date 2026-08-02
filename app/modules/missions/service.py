import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.models.user import User

logger = logging.getLogger(__name__)

# Fuso usado só pra definir o corte da semana (app é majoritariamente
# Brasil, decisão confirmada com o usuário) -- segunda-feira 00h no horário
# de Brasília, não 00h UTC (que cairia domingo às 21h aqui). Os timestamps
# continuam armazenados/comparados em UTC como o resto do projeto; BR_TZ só
# entra no cálculo de onde a semana começa e termina.
BR_TZ = ZoneInfo("America/Sao_Paulo")

# Missão "Minere 10x essa semana" -- única missão do sistema por ora (sem
# motor genérico de múltiplas missões: seria abstração sem uso real hoje --
# revisitar se/quando surgir uma segunda missão).
WEEKLY_MISSION_TARGET = 10

# Multiplicador de recompensa ganho ao completar a missão, válido pelas
# próximas WEEKLY_MISSION_MULTIPLIER_DURATION a partir do momento da
# conclusão -- NÃO se aplica à própria coleta que completa a missão
# (decisão confirmada com o usuário: só as coletas SEGUINTES, dentro da
# janela). Lido e aplicado por collect_mining_session
# (app/modules/mining/service.py), multiplicado em cadeia com o bônus do
# Cubo Épico quando os dois coincidem na mesma coleta -- decisão
# confirmada: empilhamento multiplicativo (reward * 1.25 * 1.5), não
# aditivo.
WEEKLY_MISSION_MULTIPLIER = Decimal("1.5")
WEEKLY_MISSION_MULTIPLIER_DURATION = timedelta(hours=24)


@dataclass
class WeeklyMissionStatus:
    target: int
    progress: int
    completed: bool
    week_start: datetime
    week_end: datetime
    multiplier: Decimal
    multiplier_active: bool
    multiplier_expires_at: datetime | None


def _week_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """[início, fim) da semana corrente em UTC, com o corte alinhado à
    meia-noite de segunda-feira no horário de Brasília (ver BR_TZ) -- não
    00h UTC, que na prática cairia domingo às 21h aqui."""
    now = now or datetime.now(timezone.utc)
    now_brt = now.astimezone(BR_TZ)
    monday_brt = (now_brt - timedelta(days=now_brt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start = monday_brt.astimezone(timezone.utc)
    end = (monday_brt + timedelta(days=7)).astimezone(timezone.utc)
    return start, end


def weekly_collections_count(db: Session, user_id: int, start: datetime, end: datetime) -> int:
    """Quantos ciclos de mineração o usuário coletou com sucesso na janela
    -- 1 LedgerEntry `reward` = 1 coleta bem-sucedida (ver
    collect_mining_session), então conta direto no ledger em vez de manter
    um contador à parte pra duplicar esse número (mesmo padrão que o
    ranking já usa pros totais mensais, ver _monthly_totals em
    app/modules/ranking/service.py)."""
    return (
        db.query(LedgerEntry)
        .filter(
            LedgerEntry.user_id == user_id,
            LedgerEntry.type == LedgerEntryType.REWARD,
            LedgerEntry.created_at >= start,
            LedgerEntry.created_at < end,
        )
        .count()
    )


def is_multiplier_active(user: User, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return user.weekly_mission_multiplier_until is not None and now < user.weekly_mission_multiplier_until


def get_weekly_mission_status(db: Session, user: User, now: datetime | None = None) -> WeeklyMissionStatus:
    now = now or datetime.now(timezone.utc)
    start, end = _week_window(now)
    count = weekly_collections_count(db, user.id, start, end)
    return WeeklyMissionStatus(
        target=WEEKLY_MISSION_TARGET,
        progress=min(count, WEEKLY_MISSION_TARGET),
        completed=count >= WEEKLY_MISSION_TARGET,
        week_start=start,
        week_end=end,
        multiplier=WEEKLY_MISSION_MULTIPLIER,
        multiplier_active=is_multiplier_active(user, now),
        multiplier_expires_at=user.weekly_mission_multiplier_until,
    )


def maybe_activate_weekly_mission(db: Session, user: User, now: datetime | None = None) -> bool:
    """Chamada por collect_mining_session logo APÓS gravar o LedgerEntry
    `reward` desta coleta (mesma transação/lock de usuário, sem commit
    próprio -- quem chama controla o commit). Se essa coleta foi
    exatamente a WEEKLY_MISSION_TARGET-ésima da semana, ativa o
    multiplicador por WEEKLY_MISSION_MULTIPLIER_DURATION a partir de agora.

    "== target" (não ">="): sem isso, toda coleta depois da 10ª reativaria
    a janela de 24h de novo, e a missão nunca teria uma conclusão única e
    previsível por semana. Como a contagem só cresce 1 por chamada, o
    instante em que ela cruza de target-1 pra target acontece no máximo
    uma vez por semana.

    PENDÊNCIA CONHECIDA (mesma classe de race já aceita em
    _consume_bonus_ad_view, app/modules/mining/service.py): duas coletas
    concorrentes do MESMO usuário em cubos diferentes podem, em teoria,
    cada uma contar sem ver o flush ainda não commitado da outra (READ
    COMMITTED), atrasando em no máximo 1 coleta o instante em que a missão
    é detectada como completa naquela semana -- nunca ativa cedo demais
    nem duas vezes por engano, só possivelmente 1 coleta depois da 10ª
    literal. Aceito por ora pela mesma razão: só explorável em
    concorrência real, sem impacto de segurança, e o fix (lock de linha em
    `users` já é tomado por create_ledger_entry, mas antes desta contagem
    rodar) não compensa a complexidade extra pra esse edge case.

    Retorna True se ativou agora (só pra log/teste); False nos demais
    casos, incluindo quando a missão já tinha sido completada antes."""
    now = now or datetime.now(timezone.utc)
    start, end = _week_window(now)
    count = weekly_collections_count(db, user.id, start, end)
    if count == WEEKLY_MISSION_TARGET:
        user.weekly_mission_multiplier_until = now + WEEKLY_MISSION_MULTIPLIER_DURATION
        logger.info(
            "weekly mission completed for user %s, multiplier active until %s",
            user.id,
            user.weekly_mission_multiplier_until,
        )
        return True
    return False
