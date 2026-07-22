from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CubeType:
    COMUM = "comum"
    RARO = "raro"
    EPICO = "epico"
    LENDARIO = "lendario"
    MITICO = "mitico"

    ALL = (COMUM, RARO, EPICO, LENDARIO, MITICO)


_TYPE_LIST_SQL = ", ".join(f"'{value}'" for value in CubeType.ALL)


class Cube(Base):
    __tablename__ = "cubes"
    __table_args__ = (
        CheckConstraint(f"type IN ({_TYPE_LIST_SQL})", name="ck_cubes_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    speed: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    bonus_chance: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
