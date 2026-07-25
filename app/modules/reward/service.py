import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

from sqlalchemy.orm import Session

from app.core.admob import admob_client
from app.core.config import settings
from app.models.reward_config import SINGLETON_ID, RewardConfig

logger = logging.getLogger(__name__)

# Faixa de segurança para o valor por sessão calculado a partir do eCPM
# (seção 7): protege contra um dado anômalo/corrompido vindo da AdMob
# Reporting API (ex: eCPM absurdamente alto num dia de pico) resultar num
# valor de recompensa fora do que o produto suporta. Mesmos limites usados
# antes desta integração (sorteio aleatório fixo em mining/service.py).
MIN_REWARD = Decimal("0.10")
MAX_REWARD = Decimal("1.00")


def get_current_reward_config(db: Session) -> RewardConfig:
    config = db.query(RewardConfig).filter(RewardConfig.id == SINGLETON_ID).first()
    if config is None:
        # Não deveria acontecer fora de um banco sem a migration aplicada --
        # a linha singleton é semeada pela própria migration que cria a
        # tabela (ver alembic/versions/..._add_reward_config_table.py).
        raise RuntimeError("reward_config singleton row is missing -- run migrations")
    return config


def get_current_value_per_session(db: Session) -> Decimal:
    """Usado por collect_mining_session (seção 7) para saber quanto creditar
    no ledger -- sempre o valor vigente na reward_config, nunca um valor
    fixo hardcoded."""
    return get_current_reward_config(db).value_per_session


def compute_value_per_session(avg_ecpm: Decimal) -> Decimal:
    """valor_por_sessao = (eCPM_medio * ADMOB_REWARD_MARGIN) / 1000, com
    arredondamento para baixo (nunca a favor do usuário) e sujeito à faixa
    de segurança MIN_REWARD/MAX_REWARD."""
    raw = (avg_ecpm * settings.ADMOB_REWARD_MARGIN) / Decimal("1000")
    clamped = max(MIN_REWARD, min(MAX_REWARD, raw))
    return clamped.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def update_reward_config_from_admob(db: Session, *, for_date: date | None = None) -> RewardConfig:
    """Lógica do worker diário update_reward_config (seção 7): busca o eCPM
    médio do dia anterior (por padrão) no bloco de anúncios premiado via
    AdMob Reporting API, calcula o novo valor por sessão e atualiza a
    reward_config. Chamada tanto pelo Celery beat (1x/dia, ver
    app/workers/tasks.py) quanto pelo endpoint de diagnóstico manual
    GET /admin/update-reward-config (ver app/modules/admin/router.py).

    Se a AdMob não tiver nenhum dado para o dia (ex: bloco sem impressões),
    mantém a reward_config vigente inalterada em vez de zerar o valor por
    sessão -- ausência de dado não deve ser interpretada como eCPM zero."""
    target_date = for_date or (datetime.now(timezone.utc).date() - timedelta(days=1))

    avg_ecpm = admob_client.get_average_ecpm(target_date)
    config = db.query(RewardConfig).filter(RewardConfig.id == SINGLETON_ID).with_for_update().first()
    if config is None:
        raise RuntimeError("reward_config singleton row is missing -- run migrations")

    if avg_ecpm is None:
        logger.warning("no AdMob eCPM data for %s -- keeping reward_config unchanged", target_date)
        return config

    config.value_per_session = compute_value_per_session(avg_ecpm)
    config.avg_ecpm = avg_ecpm.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    config.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config)
    return config
