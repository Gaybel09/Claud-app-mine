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
