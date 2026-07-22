from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdViewStatus:
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"

    ALL = (PENDING, CONFIRMED, REJECTED)


class AdView(Base):
    __tablename__ = "ad_views"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'confirmed', 'rejected')", name="ck_ad_views_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    ad_network: Mapped[str] = mapped_column(String(50), nullable=False)
    watched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # Correção v2 (seção 5): criado como pending quando o cliente avisa que
    # assistiu; só vira confirmed via callback assíncrono do SDK de anúncios.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AdViewStatus.PENDING, server_default=AdViewStatus.PENDING, index=True
    )
