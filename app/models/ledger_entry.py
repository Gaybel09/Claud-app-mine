from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LedgerEntryType:
    REWARD = "reward"
    WITHDRAWAL = "withdrawal"
    BONUS = "bonus"
    FEE = "fee"

    ALL = (REWARD, WITHDRAWAL, BONUS, FEE)


class LedgerEntry(Base):
    """Livro-razão do usuário. Imutável por design: só insert, nunca update ou
    delete. O saldo do usuário é sempre a soma destas linhas — nenhum módulo
    deve gravar ou expor um endpoint de alteração destes registros."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("type IN ('reward', 'withdrawal', 'bonus', 'fee')", name="ck_ledger_entries_type"),
        Index("ix_ledger_entries_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
