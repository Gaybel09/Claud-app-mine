from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WithdrawalStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"

    ALL = (PENDING, PROCESSING, PAID, FAILED)


class Withdrawal(Base):
    """Saque via Pix (seção 11). O saldo só é debitado quando status vira
    paid (webhook da Efí confirma) -- nunca no momento da criação."""

    __tablename__ = "withdrawals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'paid', 'failed')", name="ck_withdrawals_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    pix_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WithdrawalStatus.PENDING, server_default=WithdrawalStatus.PENDING, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # idEnvio de verdade enviado à Efí -- derivado de idempotency_key (ver
    # app.core.efi.derive_id_envio), porque a Efí só aceita
    # ^[a-zA-Z0-9]{1,35}$ e idempotency_key pode ser qualquer string (ex: um
    # UUID com hífens). Usado tanto no envio quanto na consulta/webhook, para
    # a idempotência real da Efí (mesmo idEnvio nunca duplica o pagamento)
    # continuar valendo mesmo com uma idempotency_key não-alfanumérica.
    efi_id_envio: Mapped[str] = mapped_column(String(35), nullable=False, unique=True, index=True)
    # Motivo reportado pela Efí quando status vira failed -- só preenchido
    # nesse caso, nunca exposto na API pública (WithdrawalRead), só no
    # endpoint de diagnóstico admin/smoke-test.
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
