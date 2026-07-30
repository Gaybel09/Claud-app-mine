import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ad_view import AdView
from app.models.cube import Cube
from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.models.mining_session import MiningSession, MiningSessionStatus
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.modules.ads.service import is_ad_confirmed
from app.modules.reward.service import get_current_value_per_session
from app.modules.wallet.service import create_ledger_entry

logger = logging.getLogger(__name__)

# Seção 8: "soma_esperada_de_payouts <= fundo.balance * margem_de_segurança".
REWARD_FUND_SAFETY_MARGIN = Decimal("0.9")

# Cubo Épico (anúncio bônus): +25% sobre o value_per_session vigente para a
# sessão que usar o bônus -- não "75% do eCPM combinado dos dois anúncios"
# (isso daria 3x, não 1.25x; eCPM real não é rastreado por anúncio
# individual, só a média diária que já alimenta value_per_session, então
# "combinar o eCPM dos dois anúncios" nem seria possível de calcular de
# verdade). Decisão explícita do produto: prioriza não acelerar o consumo
# do reward_fund em vez de maximizar a fatia repassada ao usuário nessa
# sessão.
EPIC_BONUS_MULTIPLIER = Decimal("1.25")

# Fluxo de desbloqueio: precisa de 2 RewardedAds distintos (não 1) antes de
# epic_bonus_applied virar true -- ver apply_epic_bonus.
EPIC_BONUS_VIDEOS_REQUIRED = 2

# Acelerar (2x): reduz o tempo restante pela metade -- não "acelera o
# clock" de verdade, só reagenda ends_at pra now() + metade do que faltava.
# float, não Decimal -- timedelta só aceita multiplicar por int/float.
SPEEDUP_FACTOR = 0.5


def _mining_session_duration() -> timedelta:
    """Lida do settings a cada chamada (não congelada num módulo-level
    constante) -- ver MINING_SESSION_DURATION_SECONDS em app/core/config.py
    (30min, valor definitivo de produção) para o porquê de continuar
    configurável em vez de uma constante fixa."""
    return timedelta(seconds=settings.MINING_SESSION_DURATION_SECONDS)


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


class EpicBonusAlreadyUsedError(MiningError):
    """Cubo Épico já foi usado nesta sessão -- ver apply_epic_bonus.
    Idempotência por estado (epic_bonus_applied), não por Idempotency-Key:
    uma segunda tentativa (retry de rede, duplo clique) sempre bate nesta
    checagem, nunca aplica o bônus duas vezes."""


class SpeedupAlreadyUsedError(MiningError):
    """Acelerar já foi usado nesta sessão -- ver apply_speedup. Mesma
    idempotência por estado (speedup_used) de EpicBonusAlreadyUsedError."""


class NothingToSpeedUpError(MiningError):
    """A sessão já chegou em ends_at (pronta pra coletar ou já coletada/
    expirada) -- não há mais tempo restante pra reduzir pela metade."""


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
        ends_at=started_at + _mining_session_duration(),
        status=MiningSessionStatus.RUNNING,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    _schedule_ready_notification(session)

    return session


def _consume_bonus_ad_view(db: Session, user_id: int, ad_view_id: int) -> None:
    """Validação compartilhada por apply_epic_bonus/apply_speedup: o
    ad_view precisa (1) existir e pertencer a quem está chamando, (2) estar
    confirmado (mesmo callback assíncrono do SDK usado por
    start_mining_session -- nunca só o aviso do cliente), e (3) nunca ter
    sido consumido antes, nem pra iniciar uma sessão (MiningSession.ad_view_id)
    nem pro outro slot do mesmo bônus nem pro outro bônus
    (epic_bonus_ad_view_1_id/epic_bonus_ad_view_2_id/speedup_ad_view_id) -- sem
    isso, um único anúncio assistido poderia "pagar" duas vezes.

    PENDÊNCIA CONHECIDA (baixa prioridade, aceita por ora -- revisar mais
    pra frente): a checagem "já usado" abaixo é uma leitura sem lock, então
    duas chamadas concorrentes referenciando o MESMO ad_view_id mas
    SESSÕES DIFERENTES (ex: epic-bonus na sessão A e speedup na sessão B ao
    mesmo tempo) poderiam, em teoria, passar as duas antes de qualquer uma
    commitar -- consumindo o mesmo ad_view duas vezes. O lock de linha em
    apply_epic_bonus/apply_speedup (with_for_update no MiningSession) só
    serializa chamadas para a MESMA sessão, não protege entre sessões
    diferentes. Só explorável via cliente malicioso forjando requisições
    cruas (o app legítimo sempre gera um ad_view novo antes de cada ação) --
    mesmo padrão (e mesmo risco aceito) já existente em start_mining_session
    (linha ~141 acima) desde antes deste módulo existir. Fix real, se algum
    dia justificar a prioridade: with_for_update() na própria linha de
    AdView (não só no MiningSession) antes da checagem, nos três pontos de
    consumo (start/epic-bonus/speedup)."""
    if not is_ad_confirmed(db, ad_view_id):
        raise AdViewNotConfirmedError()

    ad_view = db.query(AdView).filter(AdView.id == ad_view_id).first()
    if ad_view is None or ad_view.user_id != user_id:
        raise AdViewNotConfirmedError()

    already_used = (
        db.query(MiningSession)
        .filter(
            or_(
                MiningSession.ad_view_id == ad_view_id,
                MiningSession.epic_bonus_ad_view_1_id == ad_view_id,
                MiningSession.epic_bonus_ad_view_2_id == ad_view_id,
                MiningSession.speedup_ad_view_id == ad_view_id,
            )
        )
        .first()
    )
    if already_used is not None:
        raise AdViewAlreadyUsedError()


def apply_epic_bonus(db: Session, user_id: int, session_id: int, ad_view_id: int) -> MiningSession:
    """Cubo Épico (anúncio bônus, seção 7) -- fluxo de desbloqueio: exige 2
    RewardedAds distintos (EPIC_BONUS_VIDEOS_REQUIRED) enquanto uma
    mineração normal já está rodando antes da sessão passar a pagar
    EPIC_BONUS_MULTIPLIER (1.25x) o value_per_session vigente no momento da
    coleta. Esta função é chamada uma vez POR VÍDEO -- a primeira chamada
    preenche epic_bonus_ad_view_1_id (session.epic_bonus_videos_watched
    vira 1, ainda não aplica nada); a segunda preenche
    epic_bonus_ad_view_2_id e só aí marca epic_bonus_applied=true. O
    multiplicador de verdade só é lido em collect_mining_session, no
    momento da coleta (o valor por sessão pode mudar entre o desbloqueio e
    a coleta -- 1x/dia, ver reward.service).

    Levanta SessionNotFoundError, SessionNotReadyError (sessão não está
    RUNNING -- já coletada/expirada), EpicBonusAlreadyUsedError (já
    destravado -- os dois vídeos já foram assistidos), AdViewNotConfirmedError
    ou AdViewAlreadyUsedError (ver _consume_bonus_ad_view -- inclui usar o
    MESMO ad_view pros dois slots, já que o slot 1 já preenchido conta como
    "usado" pra essa checagem)."""
    session = (
        db.query(MiningSession)
        .filter(MiningSession.id == session_id, MiningSession.user_id == user_id)
        .with_for_update()
        .first()
    )
    if session is None:
        raise SessionNotFoundError()
    if session.status != MiningSessionStatus.RUNNING:
        raise SessionNotReadyError()
    if session.epic_bonus_applied:
        raise EpicBonusAlreadyUsedError()

    _consume_bonus_ad_view(db, user_id, ad_view_id)

    if session.epic_bonus_ad_view_1_id is None:
        session.epic_bonus_ad_view_1_id = ad_view_id
    else:
        session.epic_bonus_ad_view_2_id = ad_view_id
        session.epic_bonus_applied = True

    db.commit()
    db.refresh(session)
    return session


def apply_speedup(db: Session, user_id: int, session_id: int, ad_view_id: int) -> MiningSession:
    """Acelerar (2x, seção 7): usuário assiste um RewardedAd enquanto a
    mineração roda para reduzir o tempo restante pela metade
    (ends_at -> now() + (ends_at - now())/2). Só 1x por sessão
    (speedup_used).

    Levanta SessionNotFoundError, SessionNotReadyError (sessão não está
    RUNNING), SpeedupAlreadyUsedError, NothingToSpeedUpError (já não há
    tempo restante -- ends_at já passou), AdViewNotConfirmedError ou
    AdViewAlreadyUsedError (ver _consume_bonus_ad_view)."""
    session = (
        db.query(MiningSession)
        .filter(MiningSession.id == session_id, MiningSession.user_id == user_id)
        .with_for_update()
        .first()
    )
    if session is None:
        raise SessionNotFoundError()
    if session.status != MiningSessionStatus.RUNNING:
        raise SessionNotReadyError()
    if session.speedup_used:
        raise SpeedupAlreadyUsedError()

    now = datetime.now(timezone.utc)
    remaining = session.ends_at - now
    if remaining <= timedelta(0):
        raise NothingToSpeedUpError()

    _consume_bonus_ad_view(db, user_id, ad_view_id)

    session.ends_at = now + remaining * SPEEDUP_FACTOR
    session.speedup_used = True
    session.speedup_ad_view_id = ad_view_id
    db.commit()
    db.refresh(session)
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


def force_session_ready_for_testing(db: Session, session_id: int) -> MiningSession | None:
    """SÓ PARA TESTE MANUAL -- ver GET /admin/mining/force-ready
    (app/modules/admin/router.py), protegida por ENABLE_DIAGNOSTIC_ENDPOINTS
    + ADMIN_SMOKE_TEST_TOKEN, igual aos outros diagnósticos.

    Adianta ends_at de UMA sessão específica para o passado -- mesma técnica
    que app/modules/admin/smoke_test.py já usa internamente para não
    esperar os 30min reais (MINING_SESSION_DURATION_SECONDS, app/core/config.py).
    Prefira este endpoint quando bastar liberar UMA sessão específica: ele
    só mexe numa sessão por vez, sob demanda, e nunca toca em
    MINING_SESSION_DURATION_SECONDS nem no status da sessão -- mudar aquele
    valor direto afeta o tempo de mineração de TODO MUNDO em produção.
    "Pronto para coletar"
    continua sendo sempre calculado on-the-fly (now() >= ends_at), nunca
    persistido (correção v2, seção 5)."""
    session = db.query(MiningSession).filter(MiningSession.id == session_id).with_for_update().first()
    if session is None:
        return None
    session.ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.refresh(session)
    return session


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
    if session.epic_bonus_applied:
        # Cubo Épico -- ver apply_epic_bonus/EPIC_BONUS_MULTIPLIER. Lido do
        # value_per_session VIGENTE agora (na coleta), não do valor de quando
        # o bônus foi aplicado -- reward_config pode ter mudado entre os
        # dois momentos (recalculada 1x/dia). ROUND_DOWN (nunca a favor do
        # usuário), mesmo critério de compute_value_per_session.
        reward_amount = (reward_amount * EPIC_BONUS_MULTIPLIER).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
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
