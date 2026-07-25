from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.modules.wallet.service import compute_balance


class AdminError(Exception):
    """Base para os erros de negócio do painel admin."""


class UserNotFoundError(AdminError):
    pass


def list_users(db: Session, page: int, page_size: int) -> tuple[list[dict], int]:
    total = db.query(func.count(User.id)).scalar()
    users = (
        db.query(User)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        {
            "id": user.id,
            "email": user.email,
            "balance": compute_balance(db, user.id),
            "created_at": user.created_at,
            "is_blocked": user.is_blocked,
            "is_admin": user.is_admin,
        }
        for user in users
    ]
    return items, total


def block_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if user is None:
        raise UserNotFoundError()
    user.is_blocked = True
    db.commit()
    db.refresh(user)
    return user


def unblock_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if user is None:
        raise UserNotFoundError()
    user.is_blocked = False
    db.commit()
    db.refresh(user)
    return user


def list_withdrawals(
    db: Session, page: int, page_size: int, status_filter: str | None = None
) -> tuple[list[Withdrawal], int]:
    query = db.query(Withdrawal)
    if status_filter is not None:
        query = query.filter(Withdrawal.status == status_filter)
    total = query.with_entities(func.count(Withdrawal.id)).scalar()
    items = (
        query.order_by(Withdrawal.created_at.desc(), Withdrawal.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_user_devices(db: Session, user_id: int) -> dict:
    """Sinal básico de antifraude (seção 11): quantos usuários distintos
    compartilham o mesmo device_id do usuário consultado. Não bloqueia
    nada automaticamente -- só visibilidade pro admin decidir (ex:
    POST /admin/users/{id}/block manual em cima do que ver aqui)."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise UserNotFoundError()

    if user.device_id is None:
        return {"user_id": user.id, "device_id": None, "shared_user_count": 0, "shared_users": []}

    sharing_users = (
        db.query(User)
        .filter(User.device_id == user.device_id)
        .order_by(User.created_at.asc())
        .all()
    )
    return {
        "user_id": user.id,
        "device_id": user.device_id,
        "shared_user_count": len(sharing_users),
        "shared_users": [
            {
                "id": u.id,
                "email": u.email,
                "created_at": u.created_at,
                "is_blocked": u.is_blocked,
            }
            for u in sharing_users
        ],
    }


def get_fund_status(db: Session) -> dict:
    fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
    balance = fund.balance if fund is not None else 0
    total_in = fund.total_in if fund is not None else 0
    total_out = fund.total_out if fund is not None else 0
    threshold = settings.ADMIN_FUND_LOW_THRESHOLD
    return {
        "balance": balance,
        "total_in": total_in,
        "total_out": total_out,
        "low_balance_alert": balance < threshold,
        "low_balance_threshold": threshold,
    }
