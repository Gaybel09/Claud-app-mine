#!/usr/bin/env python3
"""Dispara GET /admin/update-reward-config (seção 7) via HTTP -- usado como
o startCommand do Render Cron Job "cubemine-pix-update-reward-config" (ver
render.yaml), agendado para rodar 1x/dia.

Por quê um script HTTP simples e não Celery Beat de verdade: a lógica real
(buscar o eCPM médio na AdMob Reporting API, recalcular reward_config) já
mora inteira dentro da própria API (app/modules/reward/service.py) e já é
exercitada pelo endpoint admin, que já existia para diagnóstico manual.
Reaproveitar esse endpoint via um Cron Job (container efêmero, cobrado só
pelos poucos segundos que roda) é bem mais barato do que manter um
Background Worker rodando 24/7 só para o Celery Beat verificar o
agendamento -- overkill para uma única tarefa diária num app pequeno no
plano free/starter do Render. Se no futuro existirem várias tarefas
periódicas diferentes, vale reconsiderar migrar para Celery Beat de
verdade (o beat_schedule em app/workers/celery_app.py já está pronto,
inclusive com a tarefa reconcile_pending_withdrawals que também não roda
em produção ainda).

Sai com código != 0 em qualquer falha (HTTP != 200, corpo com "ok": false,
ou variável de ambiente faltando) -- é assim que o Render marca a execução
do Cron Job como falha no dashboard; sem isso, uma falha ficaria silenciosa.
"""

import os
import sys

import httpx

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://cubemine-pix-api.onrender.com").rstrip("/")
ADMIN_SMOKE_TEST_TOKEN = os.environ.get("ADMIN_SMOKE_TEST_TOKEN")

REQUEST_TIMEOUT = 60


def main() -> None:
    if not ADMIN_SMOKE_TEST_TOKEN:
        print("ADMIN_SMOKE_TEST_TOKEN não configurado -- não dá pra chamar o endpoint admin.")
        sys.exit(1)

    response = httpx.get(
        f"{PUBLIC_BASE_URL}/admin/update-reward-config",
        headers={"X-Admin-Token": ADMIN_SMOKE_TEST_TOKEN},
        timeout=REQUEST_TIMEOUT,
    )
    print(f"GET /admin/update-reward-config -> {response.status_code} {response.text}")

    if response.status_code != 200:
        sys.exit(1)

    body = response.json()
    if not body.get("ok"):
        print(f"Worker reportou falha: {body.get('error')}")
        sys.exit(1)

    print(
        f"reward_config atualizada: value_per_session={body.get('value_per_session')} "
        f"avg_ecpm={body.get('avg_ecpm')}"
    )


if __name__ == "__main__":
    main()
