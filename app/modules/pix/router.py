from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.efi import EfiApiError, EfiConfigurationError, efi_client
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.modules.pix import service
from app.schemas.pix import PixWebhookRequest, PixWithdrawRequest, WithdrawalRead

router = APIRouter(prefix="/pix", tags=["pix"])


@router.get("/health")
def pix_health():
    """Diagnóstico: confirma que a autenticação OAuth2 com a Efí está
    funcionando de verdade (client_id/secret/certificado), sem precisar
    fazer um saque real. Não expõe token nem qualquer credencial na
    resposta -- só sucesso/falha."""
    try:
        efi_client.check_auth()
    except EfiConfigurationError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Efi credentials not configured")
    except EfiApiError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Efi authentication failed (HTTP {exc.status_code})"
        )
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Unexpected error contacting Efi")
    return {"status": "ok", "detail": "Efi OAuth2 authentication succeeded"}


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

    error = payload.gnExtras.error if payload.gnExtras else None
    failure_reason = f"{error.codigo}: {error.motivo}" if error else None

    withdrawal = service.apply_efi_status(
        db, id_envio=id_envio, efi_status=payload.status, failure_reason=failure_reason
    )
    if withdrawal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "withdrawal not found")
    return {"status": "ok"}
