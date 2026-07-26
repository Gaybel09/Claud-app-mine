from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SINGLETON_ID = 1

# Valor de sessão inicial, usado até a primeira execução do worker diário
# (update_reward_config, seção 7) rodar e substituí-lo pelo valor calculado a
# partir do eCPM médio real do AdMob -- ver app/modules/reward/service.py.
DEFAULT_VALUE_PER_SESSION = Decimal("0.30")


class RewardConfig(Base):
    """Linha única (id fixo em 1, reforçado por CHECK, mesmo padrão de
    RewardFund) com o valor de recompensa por sessão de mineração vigente.

    Recalculado 1x por dia pelo worker update_reward_config a partir do eCPM
    médio do dia anterior do bloco de anúncios premiado (AdMob Reporting
    API) -- ver app/modules/reward/service.py e app/core/admob.py. Lido por
    GET /reward/current (público, para o app mostrar antes de minerar) e
    por collect_mining_session (para saber quanto creditar no ledger).
    """

    __tablename__ = "reward_config"
    __table_args__ = (CheckConstraint(f"id = {SINGLETON_ID}", name="ck_reward_config_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=SINGLETON_ID)
    value_per_session: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=DEFAULT_VALUE_PER_SESSION,
        server_default=str(DEFAULT_VALUE_PER_SESSION),
    )
    # eCPM médio usado no último cálculo, já convertido para BRL (a AdMob
    # devolve na moeda da conta -- USD nesta conta -- convertido via
    # settings.ADMOB_USD_TO_BRL_RATE antes de chegar aqui, ver
    # app/modules/reward/service.py). Null até a primeira execução
    # bem-sucedida do worker (ver seed na migration).
    avg_ecpm: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
