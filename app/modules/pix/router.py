from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.pix import service
from app.schemas.pix import PixWebhookRequest, PixWithdrawRequest, WithdrawalRead

router = APIRouter(prefix="/pix", tags=["pix"])


@router.post("/withdraw", response_model=WithdrawalRead, status_code=status.HTTP_201_CREATED)
def withdraw(
    payload: PixWithdrawRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pix_key = payload.pix_key or current_user.pix_key
    if not pix_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no pix_key provided or registered for this user")

    try:
        withdrawal, _ = service.create_withdrawal(
            db,
            user_id=current_user.id,
            amount=payload.amount,
            pix_key=pix_key,
            idempotency_key=idempotency_key,
        )
    except service.InsufficientBalanceError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "insufficient balance")
    return withdrawal


@router.get("/withdrawals", response_model=list[WithdrawalRead])
def list_withdrawals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.list_user_withdrawals(db, current_user.id)


@router.post("/webhook")
def webhook(payload: PixWebhookRequest, db: Session = Depends(get_db)):
    # Webhook da Efí (servidor-a-servidor), não do app -- por isso não exige
    # o Bearer do usuário, igual ao /ads/callback.
    id_envio = payload.gnExtras.idEnvio if payload.gnExtras else None
    if not id_envio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing gnExtras.idEnvio")

    withdrawal = service.apply_efi_status(db, id_envio=id_envio, efi_status=payload.status)
    if withdrawal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "withdrawal not found")
    return {"status": "ok"}
