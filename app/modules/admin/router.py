import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.modules.admin.register_webhook import run_register_efi_webhook
from app.modules.admin.smoke_test import run_pix_smoke_test

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_token(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    token: str | None = Query(None, description="Alternativa ao header X-Admin-Token, para testar via navegador (ex: celular, sem acesso a curl/terminal)."),
) -> None:
    configured_token = settings.ADMIN_SMOKE_TEST_TOKEN
    if not configured_token:
        # Fail closed: sem a variável configurada, a rota se comporta como
        # se não existisse -- nunca fica acessível "por padrão".
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    header_ok = bool(x_admin_token) and secrets.compare_digest(x_admin_token, configured_token)
    query_ok = bool(token) and secrets.compare_digest(token, configured_token)
    if not header_ok and not query_ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid admin token")


@router.get("/smoke-test/pix", dependencies=[Depends(require_admin_token)])
def pix_smoke_test(
    db: Session = Depends(get_db),
    force_reconcile: bool = Query(
        False,
        description=(
            "Roda a reconciliação (mesma lógica do worker periódico "
            "pix.reconcile_pending_withdrawals) logo após o saque, em vez de "
            "esperar o agendamento -- para validar o fluxo sem depender do "
            "webhook."
        ),
    ),
):
    """Diagnóstico manual do fluxo completo (cadastro -> ... -> saque Pix),
    rodando dentro do próprio processo do backend -- ver
    app/modules/admin/smoke_test.py.

    APENAS PARA DIAGNÓSTICO EM SANDBOX. Cria dados reais (limpos ao final)
    e dispara um envio Pix real na Efí. Remova esta rota (ou pare de
    configurar ADMIN_SMOKE_TEST_TOKEN) antes de qualquer deploy de produção
    de verdade, fora de sandbox.
    """
    return run_pix_smoke_test(db, force_reconcile=force_reconcile)


@router.get("/register-efi-webhook", dependencies=[Depends(require_admin_token)])
def register_efi_webhook():
    """Registra na Efí a URL de webhook de envio de Pix
    (PUT /v2/webhook/:chave) para EFI_PAYER_PIX_KEY, apontando para
    PUBLIC_BASE_URL + "/pix/webhook" -- ver
    app/modules/admin/register_webhook.py.

    APENAS PARA DIAGNÓSTICO EM SANDBOX. Faz uma chamada real de escrita na
    conta Efí (registra/sobrescreve a URL de webhook associada à chave).
    Remova esta rota (ou pare de configurar ADMIN_SMOKE_TEST_TOKEN) antes
    de qualquer deploy de produção de verdade, fora de sandbox.
    """
    return run_register_efi_webhook()


@router.post("/promote-user/{user_id}", dependencies=[Depends(require_admin_token)])
def promote_user(user_id: int, db: Session = Depends(get_db)):
    """Dá acesso ao painel admin (is_admin=true) a um usuário -- ver
    GET /admin/users, /admin/withdrawals, /admin/fund (seção 10), que exigem
    login Firebase de um usuário com is_admin=true (não este token).

    Ferramenta de bootstrap manual: ainda não existe nenhum jeito de um
    admin promover outro pelo próprio painel. AO CONTRÁRIO de
    /admin/smoke-test/pix e /admin/register-efi-webhook, esta rota não é
    "só sandbox" -- é a única forma de criar o primeiro admin, e pode
    continuar necessária em produção de verdade até existir um fluxo de
    convite de admin de verdade. Ainda assim, reaproveita a proteção por
    ADMIN_SMOKE_TEST_TOKEN por simplicidade -- avalie separar os tokens se
    for desativar os diagnósticos de sandbox mas precisar manter esta rota.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    user.is_admin = True
    db.commit()
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


@router.post("/demote-user/{user_id}", dependencies=[Depends(require_admin_token)])
def demote_user(user_id: int, db: Session = Depends(get_db)):
    """Reverte promote_user -- remove acesso ao painel admin (is_admin=false)
    de um usuário. Útil para desfazer uma promoção feita por engano."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    user.is_admin = False
    db.commit()
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}
