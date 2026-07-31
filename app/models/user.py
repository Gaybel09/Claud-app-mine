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
    # Fingerprint básico de device (seção 11, antifraude) -- gerado e
    # persistido pelo próprio app Flutter, enviado via header X-Device-Id só
    # no cadastro (POST /auth/register), nunca atualizado depois. Múltiplas
    # contas com o mesmo device_id não são bloqueadas automaticamente --
    # é só um sinal de possível abuso, visível pro admin em
    # GET /admin/users/{id}/devices.
    device_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)

    # Ranking (app/modules/ranking/): apelido público exibido no lugar do
    # email nas listas de Top 10 -- opcional, definido pelo próprio usuário
    # (PATCH /auth/nickname). Sem unicidade forçada de propósito (mais de um
    # usuário com o mesmo apelido é só uma coincidência cosmética, não afeta
    # a lógica de ranking, que sempre usa user_id internamente).
    nickname: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # País (ISO 3166-1 alpha-2, ex: "BR") e estado/subdivisão (ISO 3166-2, ex:
    # "SP") detectados via IP no login (ver app/core/geoip.py). Atualizados a
    # cada login -- não só no cadastro -- para se autocorrigir caso a
    # primeira detecção tenha sido imprecisa (ex: rede móvel/VPN no
    # cadastro). Ambos nullable: usuários antigos (antes desta feature) ou
    # cujo IP não bate com nenhuma entrada do GeoLite2 ficam de fora do
    # ranking regional até o próximo login bem-sucedido, mas continuam
    # normalmente no ranking geral.
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
