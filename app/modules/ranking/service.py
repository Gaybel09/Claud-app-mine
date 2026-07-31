import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.models.user import User
from app.modules.mining.service import REWARD_FUND_SAFETY_MARGIN
from app.modules.wallet.service import create_ledger_entry
from app.schemas.ranking import RankingEntry, RankingRead, RegionalScopeRanking, ScopeRanking

logger = logging.getLogger(__name__)

# Prêmio mensal por posição do Top 10 (seção "Ranking") -- mesma escala nos
# dois escopos (geral e regional), aplicada de forma independente: um mesmo
# usuário pode ganhar nos dois escopos no mesmo mês (decisão confirmada com
# o usuário -- são prêmios/rankings independentes, não competem entre si).
MONTHLY_PAYOUT_SCALE = [
    Decimal("1.00"),
    Decimal("0.90"),
    Decimal("0.80"),
    Decimal("0.70"),
    Decimal("0.60"),
    Decimal("0.50"),
    Decimal("0.40"),
    Decimal("0.30"),
    Decimal("0.20"),
    Decimal("0.10"),
]

BRAZIL_STATE_NAMES = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AP": "Amapá",
    "AM": "Amazonas",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais",
    "PA": "Pará",
    "PB": "Paraíba",
    "PR": "Paraná",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul",
    "RO": "Rondônia",
    "RR": "Roraima",
    "SC": "Santa Catarina",
    "SP": "São Paulo",
    "SE": "Sergipe",
    "TO": "Tocantins",
}


def display_name(user: User) -> str:
    return user.nickname or f"Minerador #{user.id}"


def region_code_for(user: User) -> str | None:
    """Escopo regional do ranking: estado (formato "BR-UF", ex: "BR-SP")
    para usuários no Brasil com estado detectado, país (código ISO puro,
    ex: "US") para os demais -- inclusive brasileiros sem estado detectado
    ainda (cai no país "BR"). O prefixo "BR-" evita colisão entre um UF de 2
    letras e um código de país de 2 letras que por acaso coincidam (ex: "TO"
    é Tocantins E o código ISO de Tonga).

    None quando país/estado nunca foram detectados -- usuário fica de fora
    do ranking regional, mas continua normalmente no ranking geral."""
    if user.country_code is None:
        return None
    if user.country_code == "BR" and user.state_code:
        return f"BR-{user.state_code}"
    return user.country_code


def region_label_for(region_code: str) -> str:
    if region_code.startswith("BR-"):
        uf = region_code[3:]
        return BRAZIL_STATE_NAMES.get(uf, uf)
    return region_code


def _lifetime_totals(db: Session) -> list[tuple[User, Decimal]]:
    """Total histórico (soma de todos os créditos `reward`) por usuário,
    ordenado do maior pro menor -- é a métrica de ranking, tanto geral
    quanto regional (seção "Ranking"). Usa só `reward` (não `bonus`/
    `withdrawal`/`fee`) para que sacar via Pix nunca derrube a posição de
    ninguém, e para que os próprios prêmios de ranking não se autoalimentem
    no ranking do mês seguinte."""
    return (
        db.query(User, func.sum(LedgerEntry.amount))
        .join(LedgerEntry, LedgerEntry.user_id == User.id)
        .filter(LedgerEntry.type == LedgerEntryType.REWARD)
        .group_by(User.id)
        .order_by(func.sum(LedgerEntry.amount).desc(), User.id.asc())
        .all()
    )


def _scope_ranking(rows: list[tuple[User, Decimal]], current_user_id: int, limit: int) -> ScopeRanking:
    top = [
        RankingEntry(rank=position, user_id=user.id, display_name=display_name(user), total=total)
        for position, (user, total) in enumerate(rows[:limit], start=1)
    ]
    my_rank: int | None = None
    my_total = Decimal("0")
    for position, (user, total) in enumerate(rows, start=1):
        if user.id == current_user_id:
            my_rank, my_total = position, total
            break
    return ScopeRanking(top=top, my_rank=my_rank, my_total=my_total)


def get_ranking(db: Session, current_user: User, limit: int = 10) -> RankingRead:
    all_rows = _lifetime_totals(db)
    general = _scope_ranking(all_rows, current_user.id, limit)

    regional = None
    my_region_code = region_code_for(current_user)
    if my_region_code is not None:
        regional_rows = [(user, total) for user, total in all_rows if region_code_for(user) == my_region_code]
        scope = _scope_ranking(regional_rows, current_user.id, limit)
        regional = RegionalScopeRanking(
            region_code=my_region_code,
            region_label=region_label_for(my_region_code),
            **scope.model_dump(),
        )

    return RankingRead(general=general, regional=regional)


def _month_window(for_month: date | None) -> tuple[datetime, datetime]:
    """[início, fim) do mês-alvo em UTC. Por padrão, o mês anterior ao atual
    -- mesmo padrão de update_reward_config_from_admob para "ontem": o job
    roda no início de um mês fechando o mês que acabou de terminar."""
    if for_month is None:
        end = datetime.now(timezone.utc).date().replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    else:
        start = for_month.replace(day=1)
        _, days_in_month = monthrange(start.year, start.month)
        end = start + timedelta(days=days_in_month)
    return (
        datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
        datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc),
    )


def _monthly_totals(db: Session, start: datetime, end: datetime) -> list[tuple[User, Decimal]]:
    return (
        db.query(User, func.sum(LedgerEntry.amount))
        .join(LedgerEntry, LedgerEntry.user_id == User.id)
        .filter(LedgerEntry.type == LedgerEntryType.REWARD)
        .filter(LedgerEntry.created_at >= start, LedgerEntry.created_at < end)
        .group_by(User.id)
        .order_by(func.sum(LedgerEntry.amount).desc(), User.id.asc())
        .all()
    )


def _credit_ranking_bonus(db: Session, user_id: int, amount: Decimal, reference_id: str) -> str:
    """Credita um prêmio mensal de ranking, idempotente por reference_id --
    rodar o job de novo no mesmo mês (reexecução manual, ou retomada após
    uma falha parcial) nunca paga a mesma posição duas vezes.

    Retorna "already_paid" | "credited" | "insufficient_fund" em vez de
    lançar exceção quando o reward_fund não tem saldo: os prêmios são
    valores pequenos e cada posição é independente das outras, então um
    prêmio sem fundo não deve travar o pagamento dos demais (ao contrário
    da coleta de mineração, que é síncrona e por isso pode simplesmente
    recusar UMA ação do usuário -- ver InsufficientRewardFundError em
    app/modules/mining/service.py)."""
    existing = (
        db.query(LedgerEntry).filter(LedgerEntry.user_id == user_id, LedgerEntry.reference_id == reference_id).first()
    )
    if existing is not None:
        return "already_paid"

    reward_fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).with_for_update().first()
    max_allowed = reward_fund.balance * REWARD_FUND_SAFETY_MARGIN
    if amount > max_allowed:
        db.rollback()
        return "insufficient_fund"

    reward_fund.balance -= amount
    reward_fund.total_out += amount
    reward_fund.updated_at = datetime.now(timezone.utc)

    create_ledger_entry(db, user_id=user_id, type=LedgerEntryType.BONUS, amount=amount, reference_id=reference_id)
    db.commit()
    return "credited"


def run_monthly_ranking_payout(db: Session, *, for_month: date | None = None) -> dict:
    """Lógica do job mensal de ranking (seção "Ranking"): calcula o Top 10 do
    mês (geral e de cada região com pelo menos 1 usuário premiável) e
    credita o bônus de cada posição via `_credit_ranking_bonus`. Chamada
    tanto pelo Cron Job mensal (ver scripts/trigger_monthly_ranking_payout.py)
    quanto pelo endpoint admin de diagnóstico manual
    GET /admin/run-monthly-ranking-payout.

    Não existe nenhum contador "do mês" para resetar: o Top 10 do mês é
    sempre recalculado direto pela janela de datas em LedgerEntry.created_at
    (ver _month_window/_monthly_totals) -- o ranking GERAL (acumulado,
    nunca reseta) usa uma métrica totalmente separada (_lifetime_totals),
    então não há nenhum estado compartilhado entre os dois para corromper."""
    start, end = _month_window(for_month)
    month_label = start.strftime("%Y-%m")
    monthly_rows = _monthly_totals(db, start, end)

    results: dict[str, list[dict]] = {"credited": [], "already_paid": [], "insufficient_fund": []}

    def pay_top10(scope_label: str, rows: list[tuple[User, Decimal]]) -> None:
        for position, (user, total) in enumerate(rows[: len(MONTHLY_PAYOUT_SCALE)], start=1):
            amount = MONTHLY_PAYOUT_SCALE[position - 1]
            reference_id = f"ranking-bonus-{scope_label}-{month_label}-pos{position}"
            outcome = _credit_ranking_bonus(db, user.id, amount, reference_id)
            results[outcome].append(
                {
                    "scope": scope_label,
                    "position": position,
                    "user_id": user.id,
                    "amount": str(amount),
                    "monthly_total": str(total),
                }
            )

    pay_top10("geral", monthly_rows)

    regions: dict[str, list[tuple[User, Decimal]]] = {}
    for user, total in monthly_rows:
        region_code = region_code_for(user)
        if region_code is not None:
            regions.setdefault(region_code, []).append((user, total))
    for region_code, rows in regions.items():
        rows.sort(key=lambda user_total: (-user_total[1], user_total[0].id))
        pay_top10(f"regional-{region_code}", rows)

    return {"month": month_label, **results}
