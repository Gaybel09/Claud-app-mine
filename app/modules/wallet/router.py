from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.ledger_entry import LedgerEntry
from app.models.user import User
from app.modules.wallet.service import get_balance
from app.schemas.wallet import BalanceRead, StatementRead

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/balance", response_model=BalanceRead)
def balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return BalanceRead(balance=get_balance(db, current_user.id))


@router.get("/statement", response_model=StatementRead)
def statement(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base_query = db.query(LedgerEntry).filter(LedgerEntry.user_id == current_user.id)
    total = base_query.with_entities(func.count(LedgerEntry.id)).scalar()
    items = (
        base_query.order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return StatementRead(items=items, page=page, page_size=page_size, total=total)
