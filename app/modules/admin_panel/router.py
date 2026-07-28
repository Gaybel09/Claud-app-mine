from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import get_current_admin_user
from app.db.session import get_db
from app.models.user import User
from app.models.withdrawal import WithdrawalStatus
from app.modules.admin_panel import service
from app.modules.pix import service as pix_service
from app.schemas.admin import (
    AdminFundAdjustmentListRead,
    AdminFundAdjustmentRead,
    AdminFundAdjustRequest,
    AdminFundDepositRequest,
    AdminFundRead,
    AdminUserDevicesRead,
    AdminUserListRead,
    AdminWithdrawalListRead,
    AdminWithdrawalRead,
)

router = APIRouter(
    prefix="/admin", tags=["admin-panel"], dependencies=[Depends(get_current_admin_user)]
)


@router.get("/users", response_model=AdminUserListRead)
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = service.list_users(db, page=page, page_size=page_size)
    return AdminUserListRead(items=items, page=page, page_size=page_size, total=total)


@router.post("/users/{user_id}/block")
def block_user(user_id: int, db: Session = Depends(get_db)):
    try:
        user = service.block_user(db, user_id)
    except service.UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return {"id": user.id, "is_blocked": user.is_blocked}


@router.post("/users/{user_id}/unblock")
def unblock_user(user_id: int, db: Session = Depends(get_db)):
    try:
        user = service.unblock_user(db, user_id)
    except service.UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return {"id": user.id, "is_blocked": user.is_blocked}


@router.get("/users/{user_id}/devices", response_model=AdminUserDevicesRead)
def user_devices(user_id: int, db: Session = Depends(get_db)):
    """Visibilidade básica de antifraude (seção 11) -- quantos usuários
    distintos compartilham o mesmo device_id deste usuário. Não bloqueia
    nada sozinho, só sinaliza."""
    try:
        result = service.get_user_devices(db, user_id)
    except service.UserNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return AdminUserDevicesRead(**result)


@router.get("/withdrawals", response_model=AdminWithdrawalListRead)
def list_withdrawals(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if status_filter is not None and status_filter not in WithdrawalStatus.ALL:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"invalid status -- must be one of {', '.join(WithdrawalStatus.ALL)}",
        )
    items, total = service.list_withdrawals(
        db, page=page, page_size=page_size, status_filter=status_filter
    )
    return AdminWithdrawalListRead(items=items, page=page, page_size=page_size, total=total)


@router.post("/withdrawals/{withdrawal_id}/approve", response_model=AdminWithdrawalRead)
def approve_withdrawal(withdrawal_id: int, db: Session = Depends(get_db)):
    """Confirmação manual de pagamento -- ver docstring de
    pix.service.admin_approve_withdrawal para quando isso realmente se
    aplica (o fluxo normal é automático via webhook/reconciliação da Efí).
    """
    try:
        withdrawal = pix_service.admin_approve_withdrawal(db, withdrawal_id)
    except pix_service.WithdrawalNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "withdrawal not found")
    except pix_service.WithdrawalNotApprovableError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "withdrawal is already failed -- only pending/processing withdrawals can be approved",
        )
    return withdrawal


@router.post("/withdrawals/{withdrawal_id}/reconcile", response_model=AdminWithdrawalRead)
def reconcile_withdrawal(withdrawal_id: int, db: Session = Depends(get_db)):
    """Consulta o status real de um saque específico direto na Efí e aplica
    -- ver docstring de pix.service.admin_reconcile_withdrawal. Útil para
    saques presos em "processing" sem esperar o worker periódico (que hoje
    não roda como processo em produção, ver render.yaml) nem depender só
    do webhook. Não inventa nada: só reflete o que a Efí realmente reportar
    para esse saque."""
    try:
        withdrawal = pix_service.admin_reconcile_withdrawal(db, withdrawal_id)
    except pix_service.WithdrawalNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "withdrawal not found")
    except pix_service.EfiReconcileError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"failed to query Efi: {exc}")
    return withdrawal


@router.get("/fund", response_model=AdminFundRead)
def fund_status(db: Session = Depends(get_db)):
    return service.get_fund_status(db)


@router.post("/fund/deposit", response_model=AdminFundRead)
def deposit_to_fund(payload: AdminFundDepositRequest, db: Session = Depends(get_db)):
    """Registra um aporte real no reward_fund (ex: dinheiro que entrou na
    conta Efí que sustenta os pagamentos) -- ver docstring de
    service.deposit_to_fund. Só contabilidade interna; não movimenta
    dinheiro sozinho. Exige login de admin de verdade (mesma proteção das
    outras rotas deste painel), não o ADMIN_SMOKE_TEST_TOKEN."""
    try:
        return service.deposit_to_fund(db, payload.amount)
    except service.InvalidDepositAmountError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "amount must be positive")


@router.post("/fund/adjust", response_model=AdminFundAdjustmentRead)
def adjust_fund(
    payload: AdminFundAdjustRequest,
    db: Session = Depends(get_db),
    current_admin_user: User = Depends(get_current_admin_user),
):
    """Correção manual no reward_fund (ex: consertar um depósito digitado
    errado em POST /admin/fund/deposit) -- ver docstring de
    service.adjust_fund. Ao contrário do deposit, aceita valor negativo, e
    exige um motivo não vazio para manter o rastro de auditoria em
    fund_adjustments (GET /admin/fund/adjustments)."""
    try:
        return service.adjust_fund(db, current_admin_user.id, payload.amount, payload.reason)
    except service.InvalidAdjustmentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/fund/adjustments", response_model=AdminFundAdjustmentListRead)
def list_fund_adjustments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = service.list_fund_adjustments(db, page=page, page_size=page_size)
    return AdminFundAdjustmentListRead(items=items, page=page, page_size=page_size, total=total)
