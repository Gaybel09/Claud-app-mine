from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PixWithdrawRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    # Opcional: usa o pix_key cadastrado no perfil do usuário se omitido.
    pix_key: str | None = None


class WithdrawalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    amount: Decimal
    pix_key: str
    status: str
    idempotency_key: str
    created_at: datetime


class PixWebhookGnExtrasError(BaseModel):
    codigo: str | None = None
    origem: str | None = None
    motivo: str | None = None


class PixWebhookGnExtras(BaseModel):
    idEnvio: str | None = None
    error: PixWebhookGnExtrasError | None = None


class PixWebhookRequest(BaseModel):
    """Payload do webhook de envio de Pix da Efí. Ao contrário do webhook de
    cobrança recebida, o de envio não tem txid -- o identificador do envio
    (nossa idempotency_key) vem em gnExtras.idEnvio."""

    endToEndId: str | None = None
    chave: str | None = None
    tipo: str | None = None
    status: str
    valor: str | None = None
    horario: str | None = None
    gnExtras: PixWebhookGnExtras | None = None
