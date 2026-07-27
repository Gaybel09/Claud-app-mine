from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AdminUserRead(BaseModel):
    id: int
    email: str
    balance: Decimal
    created_at: datetime
    is_blocked: bool
    is_admin: bool


class AdminUserListRead(BaseModel):
    items: list[AdminUserRead]
    page: int
    page_size: int
    total: int


class AdminWithdrawalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    amount: Decimal
    pix_key: str
    status: str
    idempotency_key: str
    # Ao contrário de WithdrawalRead (API pública), o painel admin pode ver
    # o motivo de uma falha -- é justamente o dado que um admin precisa para
    # decidir se um saque preso merece POST /admin/withdrawals/{id}/approve.
    failure_reason: str | None
    created_at: datetime


class AdminWithdrawalListRead(BaseModel):
    items: list[AdminWithdrawalRead]
    page: int
    page_size: int
    total: int


class AdminFundRead(BaseModel):
    balance: Decimal
    total_in: Decimal
    total_out: Decimal
    low_balance_alert: bool
    low_balance_threshold: Decimal


class AdminFundDepositRequest(BaseModel):
    # Positivo, validado em app/modules/admin_panel/service.py -- reflete
    # dinheiro de verdade que entrou na conta (ex: um aporte via Pix na
    # conta Efí), então não é algo pra aceitar um valor negativo/zero aqui.
    amount: Decimal


class AdminSharedDeviceUserRead(BaseModel):
    id: int
    email: str
    created_at: datetime
    is_blocked: bool


class AdminUserDevicesRead(BaseModel):
    user_id: int
    device_id: str | None
    # Inclui o próprio usuário consultado -- count == 1 significa "device_id
    # não compartilhado com ninguém"; count > 1 é o sinal de possível abuso
    # (múltiplas contas no mesmo aparelho).
    shared_user_count: int
    shared_users: list[AdminSharedDeviceUserRead]
