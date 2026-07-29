from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MiningSessionStatus:
    RUNNING = "running"
    COLLECTED = "collected"
    EXPIRED = "expired"

    ALL = (RUNNING, COLLECTED, EXPIRED)


class MiningSession(Base):
    __tablename__ = "mining_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'collected', 'expired')", name="ck_mining_sessions_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    cube_id: Mapped[int] = mapped_column(ForeignKey("cubes.id"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Correção v2 (seção 5): running/collected/expired é o único enum de
    # status. NÃO existe um campo "ready_to_collect" persistido — se a sessão
    # está pronta para coleta é sempre calculado on-the-fly
    # (now() >= ends_at AND status = 'running') no momento de /mining/collect,
    # sob lock de linha, nunca lido de um campo pré-calculado.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MiningSessionStatus.RUNNING, server_default=MiningSessionStatus.RUNNING, index=True
    )
    ad_view_id: Mapped[int] = mapped_column(ForeignKey("ad_views.id"), nullable=False, index=True)

    # Cubo Épico (anúncio bônus, seção 7): +25% no reward_amount desta sessão
    # (ver EPIC_BONUS_MULTIPLIER em app/modules/mining/service.py) se o
    # usuário assistir um segundo RewardedAd enquanto a mineração roda. Só 1x
    # por sessão -- epic_bonus_applied vira true e nunca mais aceita outro
    # ad_view (ver apply_epic_bonus). epic_bonus_ad_view_id guarda qual
    # ad_view pagou o bônus, tanto pra auditoria quanto pra nunca deixar o
    # mesmo ad_view ser reaproveitado em outro uso (start/speedup).
    epic_bonus_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    epic_bonus_ad_view_id: Mapped[int | None] = mapped_column(ForeignKey("ad_views.id"), nullable=True)

    # Acelerar (2x, seção 7): reduz o tempo restante pela metade (ends_at ->
    # now + (ends_at - now)/2) se o usuário assistir um RewardedAd enquanto a
    # mineração roda. Só 1x por sessão -- speedup_used vira true e nunca mais
    # aceita outro ad_view (ver apply_speedup). Mesma lógica de
    # speedup_ad_view_id que epic_bonus_ad_view_id acima.
    speedup_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    speedup_ad_view_id: Mapped[int | None] = mapped_column(ForeignKey("ad_views.id"), nullable=True)
