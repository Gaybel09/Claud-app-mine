from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BalanceRead(BaseModel):
    balance: Decimal


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    amount: Decimal
    reference_id: str | None
    balance_after: Decimal
    created_at: datetime


class StatementRead(BaseModel):
    items: list[LedgerEntryRead]
    page: int
    page_size: int
    total: int
