from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import (
    ADS_WATCH_LIMIT_PER_IP,
    ADS_WATCH_LIMIT_PER_TOKEN,
    get_auth_token_key,
    limiter,
)
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.ad_view import AdView, AdViewStatus
from app.models.user import User
from app.modules.ads.service import apply_ad_callback
from app.schemas.ads import AdCallbackRequest, AdViewRead, AdWatchRequest

router = APIRouter(prefix="/ads", tags=["ads"])


@router.post("/watch", response_model=AdViewRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(ADS_WATCH_LIMIT_PER_IP, key_func=get_remote_address)
@limiter.limit(ADS_WATCH_LIMIT_PER_TOKEN, key_func=get_auth_token_key)
def watch(
    request: Request,
    payload: AdWatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ad_view = AdView(user_id=current_user.id, ad_network=payload.ad_network)
    db.add(ad_view)
    db.commit()
    db.refresh(ad_view)

    # =========================================================================
    # ATENÇÃO -- BLOCO TEMPORÁRIO DE DESENVOLVIMENTO (seção 7). O app Flutter
    # já integra o SDK real (google_mobile_ads, RewardedAd) e chama
    # POST /ads/callback sozinho depois de onUserEarnedReward -- ver
    # mobile/lib/controllers/mining_controller.dart. Este flag continua
    # existindo só pra cenários sem o app de verdade rodando (ex: testes
    # automatizados/diagnóstico no backend, como
    # app/modules/admin/smoke_test.py), onde não há RewardedAd nenhum pra
    # assistir. Com ADS_DEV_AUTO_CONFIRM ligada, confirma o ad_view na hora,
    # sem esperar nenhuma chamada externa a POST /ads/callback -- mesma
    # função (apply_ad_callback) que o callback de verdade usa, só chamada
    # direto daqui.
    #
    # Desligada por padrão (ver app/core/config.py). NUNCA ligue em produção
    # de verdade: sem um SDK real confirmando que o anúncio foi assistido até
    # o fim, isso destrava mineração de graça pra qualquer usuário -- FALHA
    # DE SEGURANÇA GRAVE. REMOVA este bloco (e ADS_DEV_AUTO_CONFIRM) assim
    # que houver outra forma de testar sem ele (ou aceite mantê-lo só pra
    # diagnóstico, nunca acessível em produção real).
    if settings.ADS_DEV_AUTO_CONFIRM:
        ad_view = apply_ad_callback(
            db, ad_view_id=ad_view.id, user_id=current_user.id, status=AdViewStatus.CONFIRMED
        )
    # =========================================================================

    return ad_view


@router.post("/callback", response_model=AdViewRead)
def callback(payload: AdCallbackRequest, db: Session = Depends(get_db)):
    # Pensado pra ser o callback assíncrono do SDK de anúncios (SSV --
    # server-to-server verification), chamado pelo servidor da rede de
    # anúncios direto, não pelo app -- por isso não exige o Bearer do
    # usuário. NA PRÁTICA, por enquanto, quem chama isto é o próprio app
    # Flutter (ver AdsApi.confirm em mobile/lib/services/ads_api.dart),
    # logo depois de onUserEarnedReward do RewardedAd real -- uma
    # confirmação client-side temporária, sem nenhuma verificação
    # criptográfica de que o anúncio foi assistido de verdade.
    #
    # TODO (integração real): validar a assinatura/HMAC do provedor (ex: o
    # par key_id/signature do AdMob SSV) ANTES de confiar em qualquer campo
    # do payload -- hoje aceitamos o payload como se já estivesse
    # verificado, então um cliente adulterado poderia chamar esta rota
    # direto sem nunca ter mostrado nenhum anúncio.
    ad_view = apply_ad_callback(
        db, ad_view_id=payload.ad_view_id, user_id=payload.user_id, status=payload.status
    )
    if ad_view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ad_view not found")
    return ad_view
