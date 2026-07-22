from sqlalchemy.orm import Session

from app.models.ad_view import AdView, AdViewStatus


def is_ad_confirmed(db: Session, ad_view_id: int) -> bool:
    """Usada pelo módulo mining para liberar POST /mining/start (seção 7,
    passo 3): só true quando o callback assíncrono do SDK já confirmou."""
    ad_view = db.query(AdView).filter(AdView.id == ad_view_id).first()
    return ad_view is not None and ad_view.status == AdViewStatus.CONFIRMED


def apply_ad_callback(db: Session, ad_view_id: int, user_id: int, status: str) -> AdView | None:
    """Aplica o resultado do callback assíncrono do SDK (seção 7, passo 2).

    Retorna None se o ad_view não existe ou não pertence a user_id --
    payload de callback inválido ou fora de contexto, tratado como
    "não encontrado" pelo chamador para não vazar se o ad_view existe.

    Idempotente: uma vez que o ad_view sai de pending, callbacks repetidos
    (comuns em webhooks de SSV, que costumam reentregar) não alteram o
    estado de novo -- só retornam o ad_view como está.
    """
    ad_view = db.query(AdView).filter(AdView.id == ad_view_id).with_for_update().first()
    if ad_view is None or ad_view.user_id != user_id:
        return None

    if ad_view.status == AdViewStatus.PENDING:
        ad_view.status = status
        db.commit()
        db.refresh(ad_view)

    return ad_view
