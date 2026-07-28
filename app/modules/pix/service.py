import logging
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.efi import EfiApiError, EfiConfigurationError, derive_id_envio, efi_client
from app.models.ledger_entry import LedgerEntryType
from app.models.user import User
from app.models.withdrawal import Withdrawal, WithdrawalStatus
from app.modules.wallet.service import compute_balance, create_ledger_entry

logger = logging.getLogger(__name__)

# Seção 11, correção v2: todo withdrawal parado em "processing" há mais de
# tanto tempo é reconciliado consultando a Efí diretamente, em vez de
# depender só do webhook.
RECONCILE_AFTER_MINUTES = 10

# Tamanho máximo guardado em withdrawals.failure_reason -- a mensagem de erro
# da Efí (corpo da resposta HTTP) não costuma conter segredo nenhum (é uma
# descrição do motivo da rejeição, ex: chave Pix inválida, valor abaixo do
# mínimo), mas é truncada por precaução e nunca exposta na API pública, só
# no endpoint de diagnóstico admin/smoke-test.
MAX_FAILURE_REASON_LENGTH = 500


def _describe_efi_failure(exc: EfiApiError | EfiConfigurationError) -> str:
    if isinstance(exc, EfiApiError):
        reason = f"HTTP {exc.status_code}: {exc.message}"
    else:
        reason = str(exc)
    return reason[:MAX_FAILURE_REASON_LENGTH]


def failure_reason_from_get_status(result: dict) -> str | None:
    """Extrai o motivo de falha do corpo cru devolvido por
    EfiClient.get_send_status. Duas formas documentadas, checadas nesta
    ordem:

    1. gnExtras.error.{codigo,motivo} -- mesmo campo usado pelo webhook
       (ver PixWebhookGnExtrasError em app/schemas/pix.py). Não confirmado
       que a Efí realmente devolve isso na resposta de consulta de status
       (só no webhook) -- mantido por precaução, caso apareça.
    2. "motivo" na raiz da resposta -- documentado oficialmente pela Efí
       para o endpoint de consulta de status (dev.efipay.com.br/en/docs/
       api-pix/gestao-de-pix/), ex: {"status": "NAO_REALIZADO", "motivo":
       "Negado por timeout"}. Esta é a forma real confirmada em produção.

    Mesmo com os dois, a Efí pode devolver NAO_REALIZADO sem nenhum dos
    dois campos (caso real do saque #8: resposta com endToEndId, idEnvio,
    valor, chave, status e horario, mas sem "motivo" nem "gnExtras.error")
    -- nesses casos o motivo real da falha não está disponível por esta
    via, e a única forma de confirmar é olhando o extrato/dashboard da
    própria Efí (o admin já foi avisado disso no dashboard do saque)."""
    root_motivo = result.get("motivo")
    if root_motivo:
        return str(root_motivo)[:MAX_FAILURE_REASON_LENGTH]

    gn_extras = result.get("gnExtras") or {}
    error = gn_extras.get("error") or {}
    codigo = error.get("codigo")
    motivo = error.get("motivo")
    if codigo is None and motivo is None:
        return None
    return f"{codigo}: {motivo}"[:MAX_FAILURE_REASON_LENGTH]


class PixError(Exception):
    """Base para os erros de negócio do módulo pix."""


class InsufficientBalanceError(PixError):
    pass


class UserNotFoundError(PixError):
    pass


class WithdrawalNotFoundError(PixError):
    pass


class WithdrawalNotApprovableError(PixError):
    pass


class EfiReconcileError(PixError):
    """A consulta de status na Efí falhou (credencial não configurada, Efí
    fora do ar, id_envio desconhecido, etc) -- ao contrário do worker
    periódico (que só loga e segue pro próximo saque), aqui o chamador é um
    admin esperando uma resposta na hora, então o erro é propagado em vez
    de engolido."""


def _mark_paid(db: Session, withdrawal: Withdrawal) -> None:
    create_ledger_entry(
        db,
        user_id=withdrawal.user_id,
        type=LedgerEntryType.WITHDRAWAL,
        amount=-withdrawal.amount,
        reference_id=f"withdrawal:{withdrawal.id}",
    )
    withdrawal.status = WithdrawalStatus.PAID


def create_withdrawal(
    db: Session,
    user_id: int,
    amount: Decimal,
    pix_key: str,
    idempotency_key: str,
) -> tuple[Withdrawal, bool]:
    """Cria (ou reaproveita) um saque Pix. Retorna (withdrawal, is_new).

    Idempotente por idempotency_key: uma segunda chamada com a mesma chave
    devolve o withdrawal já existente sem chamar a Efí de novo -- a única
    fonte de verdade de duplicidade é o UNIQUE em withdrawals.idempotency_key,
    não uma checagem prévia isolada (que teria uma corrida entre o SELECT e
    o INSERT).
    """
    existing = db.query(Withdrawal).filter(Withdrawal.idempotency_key == idempotency_key).first()
    if existing is not None:
        return existing, False

    # Mesmo lock de linha em users usado por create_ledger_entry (seção 6):
    # serializa concorrência por usuário, incluindo a checagem de saldo
    # disponível abaixo, que precisa ver os outros withdrawals em voo.
    user = db.query(User).filter(User.id == user_id).with_for_update().first()
    if user is None:
        raise UserNotFoundError()

    ledger_balance = compute_balance(db, user_id)
    committed = (
        db.query(func.coalesce(func.sum(Withdrawal.amount), 0))
        .filter(
            Withdrawal.user_id == user_id,
            Withdrawal.status.in_([WithdrawalStatus.PENDING, WithdrawalStatus.PROCESSING]),
        )
        .scalar()
    )
    # Saldo disponível de verdade descontando saques já em voo (pending ou
    # processing) que ainda não debitaram o ledger -- senão dá pra pedir o
    # mesmo saldo duas vezes antes de qualquer um dos dois confirmar.
    available = ledger_balance - Decimal(committed)

    if amount > available:
        raise InsufficientBalanceError()

    withdrawal = Withdrawal(
        user_id=user_id,
        amount=amount,
        pix_key=pix_key,
        status=WithdrawalStatus.PENDING,
        idempotency_key=idempotency_key,
        # A Efí só aceita idEnvio alfanumérico (^[a-zA-Z0-9]{1,35}$);
        # idempotency_key pode ser qualquer string (ex: um UUID com hífens),
        # então nunca é usada direto -- ver app.core.efi.derive_id_envio.
        efi_id_envio=derive_id_envio(idempotency_key),
    )
    db.add(withdrawal)
    db.flush()  # popula withdrawal.id antes de chamar a Efí

    try:
        efi_client.send_pix(id_envio=withdrawal.efi_id_envio, amount=amount, favorecido_chave=pix_key)
        withdrawal.status = WithdrawalStatus.PROCESSING
    except (EfiApiError, EfiConfigurationError) as exc:
        logger.warning("failed to send Pix for withdrawal %s", withdrawal.id, exc_info=True)
        withdrawal.status = WithdrawalStatus.FAILED
        withdrawal.failure_reason = _describe_efi_failure(exc)

    db.commit()
    db.refresh(withdrawal)
    return withdrawal, True


def list_user_withdrawals(db: Session, user_id: int) -> list[Withdrawal]:
    return (
        db.query(Withdrawal)
        .filter(Withdrawal.user_id == user_id)
        .order_by(Withdrawal.created_at.desc())
        .all()
    )


def apply_efi_status(
    db: Session, id_envio: str, efi_status: str, failure_reason: str | None = None
) -> Withdrawal | None:
    """Aplica o status reportado pela Efí (via webhook ou via reconciliação
    -- mesma lógica para as duas fontes) a um withdrawal.

    `id_envio` é o idEnvio de verdade devolvido pela Efí (gnExtras.idEnvio no
    webhook) -- ou seja, withdrawals.efi_id_envio, não idempotency_key (que
    pode conter caracteres que a Efí não aceita -- ver derive_id_envio).

    Só debita o ledger quando efi_status == "REALIZADO", nunca antes.
    Idempotente: um withdrawal em estado terminal (paid/failed) ignora
    novas chamadas, então um webhook duplicado -- ou um webhook chegando
    depois da reconciliação já ter resolvido o mesmo saque -- não debita
    de novo.

    failure_reason (opcional): motivo reportado pela Efí quando
    efi_status == "NAO_REALIZADO" (ex: payload.gnExtras.error do webhook).
    Se o withdrawal já estiver failed mas sem failure_reason gravado ainda
    (ex: uma reconciliação anterior que rodou antes desta função aceitar
    esse parâmetro), esta chamada faz só o backfill do motivo, sem tentar
    reaplicar a transição de status.
    """
    withdrawal = (
        db.query(Withdrawal).filter(Withdrawal.efi_id_envio == id_envio).with_for_update().first()
    )
    if withdrawal is None:
        return None

    if withdrawal.status == WithdrawalStatus.FAILED and withdrawal.failure_reason is None and failure_reason:
        withdrawal.failure_reason = failure_reason[:MAX_FAILURE_REASON_LENGTH]
        db.commit()
        db.refresh(withdrawal)
        return withdrawal

    if withdrawal.status in (WithdrawalStatus.PAID, WithdrawalStatus.FAILED):
        return withdrawal

    if efi_status == "REALIZADO":
        _mark_paid(db, withdrawal)
    elif efi_status == "NAO_REALIZADO":
        withdrawal.status = WithdrawalStatus.FAILED
        if failure_reason:
            withdrawal.failure_reason = failure_reason[:MAX_FAILURE_REASON_LENGTH]
    elif efi_status == "EM_PROCESSAMENTO":
        withdrawal.status = WithdrawalStatus.PROCESSING
    else:
        return withdrawal

    db.commit()
    db.refresh(withdrawal)
    return withdrawal


def admin_approve_withdrawal(db: Session, withdrawal_id: int) -> Withdrawal:
    """Confirma manualmente que um saque foi pago (painel admin, seção 10).

    O fluxo normal é 100% automático: a Efí confirma via webhook
    (POST /pix/webhook) ou, se o webhook não chegar, o worker periódico de
    reconciliação (pix.reconcile_pending_withdrawals) consulta o status
    direto na Efí a cada 5min para todo saque parado em "processing" há
    mais de RECONCILE_AFTER_MINUTES. Isto aqui é só a via de escape manual
    para quando as duas falharem (ex: Efí fora do ar por um tempo
    prolongado, ou algum outro motivo deixou um saque específico preso) e
    um admin já confirmou de forma independente -- olhando o extrato/
    dashboard da própria Efí -- que a transferência realmente aconteceu.

    NUNCA deve ser usada para "aprovar" um saque que ainda não foi
    confirmado de verdade na Efí: debita o saldo do usuário exatamente como
    uma confirmação real (mesmo _mark_paid de apply_efi_status), então
    aprovar um saque que na verdade falhou deixa o saldo do usuário
    incorreto.

    Idempotente (um withdrawal já pago não é debitado de novo); levanta
    WithdrawalNotFoundError se o id não existir, ou
    WithdrawalNotApprovableError se o saque já estiver em outro estado
    terminal (failed) -- só pending/processing podem ser aprovados.
    """
    withdrawal = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).with_for_update().first()
    if withdrawal is None:
        raise WithdrawalNotFoundError()
    if withdrawal.status == WithdrawalStatus.PAID:
        return withdrawal
    if withdrawal.status not in (WithdrawalStatus.PENDING, WithdrawalStatus.PROCESSING):
        raise WithdrawalNotApprovableError()

    _mark_paid(db, withdrawal)
    db.commit()
    db.refresh(withdrawal)
    return withdrawal


def admin_reconcile_withdrawal(db: Session, withdrawal_id: int) -> Withdrawal:
    """Consulta o status real de um saque específico direto na Efí e aplica
    (mesma lógica de app.workers.tasks.reconcile_withdrawal, usada pelo
    worker periódico de reconciliação) -- via de escape sob demanda para um
    admin verificar um saque preso em "processing" sem esperar o Celery Beat
    rodar (que hoje nem está implantado como processo em produção, ver
    render.yaml) nem depender só do webhook.

    Ao contrário do worker periódico, propaga EfiReconcileError se a
    consulta à Efí falhar (credencial não configurada, Efí fora do ar,
    id_envio não encontrado) -- o admin que chamou isso na hora quer saber
    se deu erro, não só um log silencioso.

    Levanta WithdrawalNotFoundError se o id não existir. SEMPRE consulta a
    Efí de verdade, mesmo que o status local já pareça terminal (paid ou
    failed) -- ao contrário do worker periódico (que só olha withdrawals em
    "processing", pra não gastar chamada à Efí à toa numa varredura
    automática de muitos saques), aqui é uma ação explícita e pontual de um
    admin, então o custo de mais uma chamada é irrelevante perto do valor
    de conseguir confirmar/completar a informação de um saque específico
    (ex: um failure_reason que ficou nulo numa reconciliação anterior a
    este fix). A segurança contra debitar duas vezes um saque já pago não
    depende de pular a consulta aqui -- fica inteiramente por conta da
    própria idempotência de apply_efi_status (que sempre confere o estado
    atual do withdrawal antes de aplicar qualquer mudança real)."""
    withdrawal = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
    if withdrawal is None:
        raise WithdrawalNotFoundError()

    try:
        result = efi_client.get_send_status(withdrawal.efi_id_envio)
    except (EfiApiError, EfiConfigurationError) as exc:
        raise EfiReconcileError(_describe_efi_failure(exc)) from exc

    # .info() nunca aparece nos logs do Render nem em nenhum outro lugar --
    # este app não configura nível de logging em lugar nenhum (nem
    # basicConfig nem dictConfig), então o root logger fica no default do
    # Python (WARNING), e .info() é descartado antes de chegar em qualquer
    # handler. .warning() é o nível mínimo que garante aparecer sem
    # depender de configuração adicional -- mesmo padrão já usado em todo
    # log "importante" deste módulo (ver _describe_efi_failure/create_withdrawal).
    logger.warning("Efi get_send_status response for withdrawal %s: %s", withdrawal.id, result)

    efi_status = result.get("status")
    if efi_status:
        apply_efi_status(
            db,
            id_envio=withdrawal.efi_id_envio,
            efi_status=efi_status,
            failure_reason=failure_reason_from_get_status(result),
        )

    db.refresh(withdrawal)
    return withdrawal
