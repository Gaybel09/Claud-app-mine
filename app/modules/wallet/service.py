from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.redis import redis_client
from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.models.user import User

BALANCE_CACHE_KEY_TEMPLATE = "wallet:balance:{user_id}"
BALANCE_CACHE_TTL_SECONDS = 60

_CREDIT_TYPES = {LedgerEntryType.REWARD, LedgerEntryType.BONUS}
_DEBIT_TYPES = {LedgerEntryType.WITHDRAWAL, LedgerEntryType.FEE}


def compute_balance(db: Session, user_id: int) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(LedgerEntry.amount), 0))
        .filter(LedgerEntry.user_id == user_id)
        .scalar()
    )
    return Decimal(total)


def cache_balance(user_id: int, balance: Decimal) -> None:
    redis_client.set(BALANCE_CACHE_KEY_TEMPLATE.format(user_id=user_id), str(balance), ex=BALANCE_CACHE_TTL_SECONDS)


def get_cached_balance(user_id: int) -> Decimal | None:
    value = redis_client.get(BALANCE_CACHE_KEY_TEMPLATE.format(user_id=user_id))
    return Decimal(value) if value is not None else None


def get_balance(db: Session, user_id: int) -> Decimal:
    balance = compute_balance(db, user_id)
    cache_balance(user_id, balance)
    return balance


def create_ledger_entry(
    db: Session,
    user_id: int,
    type: str,
    amount: Decimal,
    reference_id: str | None = None,
) -> LedgerEntry:
    """Grava uma linha imutável no ledger e retorna a entry criada.

    Não faz commit: quem chama controla os limites da transação (ex: o
    módulo mining grava a entry e marca a sessão como collected no mesmo
    commit). O lock de linha em `users` (seção 6) serializa chamadas
    concorrentes para o mesmo user_id, então o saldo lido aqui e a entry
    inserida ficam consistentes mesmo sob concorrência.
    """
    if type in _CREDIT_TYPES and amount <= 0:
        raise ValueError(f"ledger entries of type '{type}' must have a positive amount")
    if type in _DEBIT_TYPES and amount >= 0:
        raise ValueError(f"ledger entries of type '{type}' must have a negative amount")

    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if user is None:
        raise ValueError(f"user {user_id} does not exist")

    balance_after = compute_balance(db, user_id) + amount

    entry = LedgerEntry(
        user_id=user_id,
        type=type,
        amount=amount,
        reference_id=reference_id,
        balance_after=balance_after,
    )
    db.add(entry)
    db.flush()
    return entry
