import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.cube import Cube
from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.models.mining_session import MiningSession, MiningSessionStatus
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.modules.ads.service import is_ad_confirmed
from app.modules.reward.service import get_current_value_per_session
from app.modules.wallet.service import create_ledger_entry

logger = logging.getLogger(__name__)

MINING_SESSION_DURATION = timedelta(hours=2)

# Seção 8: "soma_esperada_de_payouts <= fundo.balance * margem_de_segurança".
REWARD_FUND_SAFETY_MARGIN = Decimal("0.9")


class MiningError(Exception):
    """Base para os erros de negócio do módulo mining."""


class CubeNotFoundError(MiningError):
    pass


class AdViewNotConfirmedError(MiningError):
    pass


class AdViewAlreadyUsedError(MiningError):
    pass


class CubeAlreadyMiningError(MiningError):
    """O cubo já tem uma mining_session RUNNING -- ver start_mining_session.
    Sem esta checagem, um cliente que perdesse o estado local da tela do
    cubo (ex: trocar de aba e voltar, ver mobile/lib/screens/cube/cube_screen.dart)
    podia assistir um novo anúncio e iniciar uma SEGUNDA sessão concorrente
    no mesmo cubo, multiplicando a taxa de recompensa pretendida (1 sessão
    por cubo por vez) -- falha de segurança, não só um bug de UI."""


class SessionNotFoundError(MiningError):
    pass


class SessionNotReadyError(MiningError):
    pass


class InsufficientRewardFundError(MiningError):
    pass


@dataclass
class MiningStatusResult:
    id: int
    status: str
    ends_at: datetime
    ready_to_collect: bool


def start_mining_session(db: Session, user_id: int, cube_id: int, ad_view_id: int) -> MiningSession:
    # Lock na linha do cubo (não só um SELECT simples) -- serializa chamadas
    # concorrentes de start_mining_session para o MESMO cubo, para a checagem
    # de "já tem sessão rodando" logo abaixo não ter uma janela de corrida
    # entre duas requisições que passariam na checagem antes de qualquer
    # uma commitar (mesmo padrão de lock usado em collect_mining_session e
    # create_ledger_entry).
    cube = db.query(Cube).filter(Cube.id == cube_id, Cube.user_id == user_id).with_for_update().first()
    if cube is None:
        raise CubeNotFoundError()

    # Falha de segurança corrigida: um cubo só pode ter UMA mining_session
    # RUNNING por vez. Sem isso, era possível assistir um novo anúncio e
    # iniciar uma segunda sessão concorrente enquanto a primeira ainda
    # rodava (ver CubeAlreadyMiningError).
    already_mining = (
        db.query(MiningSession)
        .filter(MiningSession.cube_id == cube_id, MiningSession.status == MiningSessionStatus.RUNNING)
        .first()
    )
    if already_mining is not None:
        raise CubeAlreadyMiningError()

    # Seção 7, passo 3: só libera após o callback assíncrono do SDK confirmar
    # -- nunca com base só no aviso do cliente.
    if not is_ad_confirmed(db, ad_view_id):
        raise AdViewNotConfirmedError()

    # Salvaguarda além do que a seção 7 descreve literalmente: um mesmo
    # ad_view confirmado só pode destravar um ciclo de mineração, senão dá
    # pra reusar a mesma visualização pra minerar indefinidamente.
    already_used = db.query(MiningSession).filter(MiningSession.ad_view_id == ad_view_id).first()
    if already_used is not None:
        raise AdViewAlreadyUsedError()

    started_at = datetime.now(timezone.utc)
    session = MiningSession(
        user_id=user_id,
        cube_id=cube_id,
        ad_view_id=ad_view_id,
        started_at=started_at,
        ends_at=started_at + MINING_SESSION_DURATION,
        status=MiningSessionStatus.RUNNING,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    _schedule_ready_notification(session)

    return session


def get_active_session_for_cube(db: Session, user_id: int, cube_id: int) -> MiningSession | None:
    """Usada por GET /mining/active-session (chamada pelo app ao carregar a
    tela do cubo) para restaurar o estado de uma mineração em andamento --
    ex: depois do usuário trocar de aba e voltar, o que reseta o estado
    local do app (ver mobile/lib/controllers/mining_controller.dart). Sem
    isso, o app não tinha como saber que já existia uma sessão rodando e
    voltava a mostrar o botão de assistir anúncio -- e, antes da correção em
    start_mining_session, isso permitia iniciar uma segunda sessão em cima
    da primeira."""
    return (
        db.query(MiningSession)
        .filter(MiningSession.cube_id == cube_id, MiningSession.user_id == user_id, MiningSession.status == MiningSessionStatus.RUNNING)
        .first()
    )


def _schedule_ready_notification(session: MiningSession) -> None:
    # Seção 7, passo 4: o worker só agenda o lembrete para ends_at, nunca
    # escreve no status da sessão.
    try:
        from app.workers.tasks import send_mining_ready_notification

        send_mining_ready_notification.apply_async(args=[session.id], eta=session.ends_at)
    except Exception:
        logger.warning("failed to schedule mining ready notification for session %s", session.id, exc_info=True)


def get_mining_status(db: Session, user_id: int, session_id: int) -> MiningStatusResult | None:
    session = (
        db.query(MiningSession)
        .filter(MiningSession.id == session_id, MiningSession.user_id == user_id)
        .first()
    )
    if session is None:
        return None

    # Correção v2 (seção 5): "pronto para coletar" nunca é lido de um campo
    # persistido -- é sempre now() >= ends_at calculado na hora, aqui e em
    # collect_mining_session.
    ready = session.status == MiningSessionStatus.RUNNING and datetime.now(timezone.utc) >= session.ends_at
    return MiningStatusResult(
        id=session.id, status=session.status, ends_at=session.ends_at, ready_to_collect=ready
    )


def collect_mining_session(db: Session, user_id: int, session_id: int) -> tuple[MiningSession, Decimal]:
    # Seção 7, passo 5: lock de linha na sessão antes de qualquer decisão.
    session = (
        db.query(MiningSession)
        .filter(MiningSession.id == session_id, MiningSession.user_id == user_id)
        .with_for_update()
        .first()
    )
    if session is None:
        raise SessionNotFoundError()

    if session.status == MiningSessionStatus.COLLECTED:
        # Idempotente: uma segunda chamada (mesma Idempotency-Key ou uma
        # requisição concorrente que ficou bloqueada no lock acima até a
        # primeira commitar) não sorteia nem credita de novo -- só devolve o
        # que já foi coletado.
        existing_entry = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.user_id == user_id, LedgerEntry.reference_id == str(session.id))
            .first()
        )
        reward_amount = existing_entry.amount if existing_entry is not None else Decimal("0")
        return session, reward_amount

    if session.status != MiningSessionStatus.RUNNING:
        raise SessionNotReadyError()

    # Nunca confia num status pré-calculado: recalcula now() >= ends_at aqui,
    # sob o lock que acabamos de tomar.
    if datetime.now(timezone.utc) < session.ends_at:
        raise SessionNotReadyError()

    reward_fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).with_for_update().first()

    # Seção 7: valor vigente da reward_config (recalculado 1x/dia a partir
    # do eCPM real do AdMob -- ver app/modules/reward/service.py), não mais
    # um sorteio aleatório fixo.
    reward_amount = get_current_value_per_session(db)
    max_allowed = reward_fund.balance * REWARD_FUND_SAFETY_MARGIN
    if reward_amount > max_allowed:
        # Falha segura: nada foi mutado ainda (nem reward_fund, nem a
        # sessão), então não há fundo negativo nem sessão collected órfã.
        raise InsufficientRewardFundError()

    reward_fund.balance -= reward_amount
    reward_fund.total_out += reward_amount
    reward_fund.updated_at = datetime.now(timezone.utc)

    create_ledger_entry(
        db,
        user_id=user_id,
        type=LedgerEntryType.REWARD,
        amount=reward_amount,
        reference_id=str(session.id),
    )

    session.status = MiningSessionStatus.COLLECTED

    # Tudo -- débito do fundo, ledger entry, status da sessão -- num único
    # commit atômico no final (seção 7, passo 6).
    db.commit()
    db.refresh(session)
    return session, reward_amount
