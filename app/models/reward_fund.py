from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SINGLETON_ID = 1


class RewardFund(Base):
    """Linha única (id fixo em 1, reforçado por CHECK) — todo lançamento de
    entrada/saída do fundo passa por lock transacional na linha."""

    __tablename__ = "reward_fund"
    __table_args__ = (CheckConstraint(f"id = {SINGLETON_ID}", name="ck_reward_fund_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=SINGLETON_ID)
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    total_in: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    total_out: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    # Soma de todos os ajustes manuais (POST /admin/fund/adjust, ver
    # app/models/fund_adjustment.py) -- positivo ou negativo, nunca tocado
    # por depósitos (total_in) nem coletas de recompensa (total_out) de
    # verdade. Mantém o invariante balance == total_in - total_out +
    # total_adjustments sempre reconciliável, mesmo depois de correções.
    total_adjustments: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
