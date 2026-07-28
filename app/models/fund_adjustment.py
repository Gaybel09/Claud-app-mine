from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FundAdjustment(Base):
    """Trilha de auditoria imutável (só insert, igual a LedgerEntry) de
    correções manuais no reward_fund (POST /admin/fund/adjust) -- para um
    admin conseguir corrigir um depósito digitado errado (POST
    /admin/fund/deposit só soma valores positivos) sem perder o rastro de
    quem, quando e por quê."""

    __tablename__ = "fund_adjustments"
    __table_args__ = (CheckConstraint("amount != 0", name="ck_fund_adjustments_amount_nonzero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Positivo ou negativo -- nunca zero (validado também em
    # app/modules/admin_panel/service.py antes do INSERT, o CHECK é só a
    # segunda camada).
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
