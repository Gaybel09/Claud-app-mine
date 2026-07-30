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

    # Cubo Épico (anúncio bônus, seção 7): fluxo de "desbloqueio" -- exige 2
    # RewardedAds distintos assistidos enquanto a mineração roda (não 1) pra
    # destravar +25% no reward_amount desta sessão (ver
    # EPIC_BONUS_MULTIPLIER em app/modules/mining/service.py).
    # epic_bonus_ad_view_1_id/epic_bonus_ad_view_2_id guardam cada um dos
    # dois ad_views (nesta ordem -- o primeiro a preencher o slot 1 vazio),
    # tanto pra auditoria quanto pra nunca deixar um ad_view ser
    # reaproveitado em outro uso (start/speedup/o outro slot). Só quando os
    # dois slots estão preenchidos é que epic_bonus_applied vira true --
    # antes disso, epic_bonus_videos_watched (ver property abaixo) reflete
    # o progresso (0, 1 ou 2) pra UI mostrar "X/2 vídeos assistidos".
    epic_bonus_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    epic_bonus_ad_view_1_id: Mapped[int | None] = mapped_column(ForeignKey("ad_views.id"), nullable=True)
    epic_bonus_ad_view_2_id: Mapped[int | None] = mapped_column(ForeignKey("ad_views.id"), nullable=True)

    # Acelerar (2x, seção 7): reduz o tempo restante pela metade (ends_at ->
    # now + (ends_at - now)/2) se o usuário assistir um RewardedAd enquanto a
    # mineração roda. Só 1x por sessão -- speedup_used vira true e nunca mais
    # aceita outro ad_view (ver apply_speedup). Mesma lógica de
    # speedup_ad_view_id que os dois epic_bonus_ad_view_*_id acima.
    speedup_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    speedup_ad_view_id: Mapped[int | None] = mapped_column(ForeignKey("ad_views.id"), nullable=True)

    @property
    def epic_bonus_videos_watched(self) -> int:
        """0, 1 ou 2 -- quantos dos dois slots de vídeo do Cubo Épico já
        foram preenchidos. Não é uma coluna própria (evita duplicar o que
        já dá pra derivar dos dois FKs acima); MiningSessionRead
        (app/schemas/mining.py) expõe isso via from_attributes, então o
        Flutter só precisa ler este campo pra mostrar "X/2 vídeos"."""
        return sum(
            1 for ad_view_id in (self.epic_bonus_ad_view_1_id, self.epic_bonus_ad_view_2_id) if ad_view_id is not None
        )
