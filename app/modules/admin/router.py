import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.modules.admin.smoke_test import run_pix_smoke_test

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin_token(x_admin_token: str | None = Header(None, alias="X-Admin-Token")) -> None:
    configured_token = settings.ADMIN_SMOKE_TEST_TOKEN
    if not configured_token:
        # Fail closed: sem a variável configurada, a rota se comporta como
        # se não existisse -- nunca fica acessível "por padrão".
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not x_admin_token or not secrets.compare_digest(x_admin_token, configured_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid admin token")


@router.get("/smoke-test/pix", dependencies=[Depends(require_admin_token)])
def pix_smoke_test(db: Session = Depends(get_db)):
    """Diagnóstico manual do fluxo completo (cadastro -> ... -> saque Pix),
    rodando dentro do próprio processo do backend -- ver
    app/modules/admin/smoke_test.py.

    APENAS PARA DIAGNÓSTICO EM SANDBOX. Cria dados reais (limpos ao final)
    e dispara um envio Pix real na Efí. Remova esta rota (ou pare de
    configurar ADMIN_SMOKE_TEST_TOKEN) antes de qualquer deploy de produção
    de verdade, fora de sandbox.
    """
    return run_pix_smoke_test(db)
