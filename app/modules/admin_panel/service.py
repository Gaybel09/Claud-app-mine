from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.fund_adjustment import FundAdjustment
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.modules.wallet.service import compute_balance


class AdminError(Exception):
    """Base para os erros de negócio do painel admin."""


class UserNotFoundError(AdminError):
    pass


class InvalidDepositAmountError(AdminError):
    pass


class InvalidAdjustmentError(AdminError):
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


def deposit_to_fund(db: Session, amount: Decimal) -> dict:
    """Aporte manual real no reward_fund -- ao contrário de
    admin/smoke_test.py's _grant_temporary_fund_headroom (que dá saldo
    fictício só durante o smoke test e desfaz ao final), este incremento é
    permanente: usado quando dinheiro de verdade entrou na conta que
    sustenta os pagamentos (ex: um aporte via Pix na conta Efí que recebe
    os saques -- ver EFI_PAYER_PIX_KEY), refletindo isso no controle
    interno de saldo do backend. Não movimenta nenhum dinheiro de verdade
    sozinho -- é só contabilidade; o aporte real acontece fora do sistema."""
    if amount <= 0:
        raise InvalidDepositAmountError("amount must be positive")

    fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).with_for_update().first()
    fund.balance += amount
    fund.total_in += amount
    db.commit()
    db.refresh(fund)
    return get_fund_status(db)


def adjust_fund(db: Session, admin_user_id: int, amount: Decimal, reason: str) -> FundAdjustment:
    """Correção manual no reward_fund (POST /admin/fund/adjust) -- ao
    contrário de deposit_to_fund, aceita valor negativo, para consertar um
    depósito digitado errado sem deixar o fundo desalinhado do saldo
    bancário real. Grava uma linha imutável em fund_adjustments (mesmo
    espírito de LedgerEntry: só insert, nunca update/delete) para não
    perder o rastro de quem fez, quando e por quê.

    NÃO mexe em total_in nem total_out -- esses dois continuam refletindo
    só depósitos/coletas reais (ver deposit_to_fund e
    mining.collect_mining_session); a correção entra à parte em
    total_adjustments, mantendo balance == total_in - total_out +
    total_adjustments sempre reconciliável."""
    if amount == 0:
        raise InvalidAdjustmentError("amount must not be zero")
    reason = reason.strip()
    if not reason:
        raise InvalidAdjustmentError("reason must not be empty")

    fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).with_for_update().first()
    fund.balance += amount
    fund.total_adjustments += amount

    adjustment = FundAdjustment(
        amount=amount,
        reason=reason,
        balance_after=fund.balance,
        admin_user_id=admin_user_id,
    )
    db.add(adjustment)
    db.commit()
    db.refresh(adjustment)
    return adjustment


def list_fund_adjustments(db: Session, page: int, page_size: int) -> tuple[list[FundAdjustment], int]:
    total = db.query(func.count(FundAdjustment.id)).scalar()
    items = (
        db.query(FundAdjustment)
        .order_by(FundAdjustment.created_at.desc(), FundAdjustment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_fund_status(db: Session) -> dict:
    fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).first()
    balance = fund.balance if fund is not None else 0
    total_in = fund.total_in if fund is not None else 0
    total_out = fund.total_out if fund is not None else 0
    total_adjustments = fund.total_adjustments if fund is not None else 0
    threshold = settings.ADMIN_FUND_LOW_THRESHOLD
    return {
        "balance": balance,
        "total_in": total_in,
        "total_out": total_out,
        "total_adjustments": total_adjustments,
        "low_balance_alert": balance < threshold,
        "low_balance_threshold": threshold,
    }
