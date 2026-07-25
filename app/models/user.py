from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KYCStatus:
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    # Informativo: pode mudar no Firebase (ex: troca de e-mail) sem afetar a
    # identidade do usuário, que é sempre firebase_uid.
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # Firebase Auth é quem detém a credencial (seção 2); mantido nullable pois
    # o backend nunca recebe/verifica senha diretamente.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pix_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    kyc_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=KYCStatus.PENDING, server_default=KYCStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Acesso ao painel admin (seção 10) -- GET/POST /admin/users,
    # /admin/withdrawals, /admin/fund. Sem jeito de um admin promover outro
    # pelo próprio painel ainda; promoção manual via
    # POST /admin/promote-user/{id} (protegida por ADMIN_SMOKE_TEST_TOKEN).
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
