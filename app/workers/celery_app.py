from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "cubemine_pix",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.task_default_queue = "cubemine_pix"

# Seção 11, correção v2: reconciliação periódica dos saques Pix presos em
# "processing" -- rede de segurança independente do webhook da Efí (que
# funciona, mas cuja confiabilidade sozinha nunca foi comprovada -- ver
# investigação do saque #10). Rodado via `celery worker --beat` (beat
# embutido no mesmo processo, ver render.yaml serviço "worker") -- um único
# processo/serviço, mais barato que separar worker e beat, seguro desde que
# esse serviço nunca seja escalado para mais de 1 instância (beat embutido
# em múltiplas instâncias dispararia a mesma tarefa mais de uma vez).
#
# 60s (não os 300s/5min originais): como este processo já fica de pé 24/7 de
# qualquer forma (cobrado por mês, não por execução -- ao contrário do Cron
# Job de update-reward-config abaixo), apertar o intervalo de checagem não
# aumenta o custo -- só reduz o pior caso de demora até uma reconciliação
# automática (ver RECONCILE_AFTER_MINUTES em app/modules/pix/service.py).
#
# update-reward-config (seção 7) NÃO está agendado aqui de propósito: já
# roda 1x/dia via o Cron Job dedicado em render.yaml (mais barato pra uma
# tarefa diária -- cobrado só pelos segundos de execução). Incluir aqui
# também faria a AdMob Reporting API ser consultada duas vezes por dia
# (uma vez por cada mecanismo) sem nenhum benefício.
celery_app.conf.beat_schedule = {
    "reconcile-pending-withdrawals": {
        "task": "pix.reconcile_pending_withdrawals",
        "schedule": 60.0,  # a cada 1 minuto
    },
}
