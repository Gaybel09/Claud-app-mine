#!/usr/bin/env python3
"""Dispara GET /admin/run-monthly-ranking-payout (seção "Ranking") via HTTP --
usado como o startCommand do Render Cron Job
"cubemine-pix-monthly-ranking-payout" (ver render.yaml), agendado para
rodar 1x/mês, no início do mês, para fechar o Top 10 do mês anterior.

Mesmo raciocínio de scripts/trigger_update_reward_config.py: a lógica real
já mora inteira dentro da própria API
(app/modules/ranking/service.py:run_monthly_ranking_payout), e reaproveitar
o endpoint admin via Cron Job (container efêmero, cobrado só pelos poucos
segundos que roda) é bem mais barato do que um Background Worker 24/7 para
uma única tarefa mensal.

Sai com código != 0 em qualquer falha (HTTP != 200 ou corpo com "ok": false)
-- é assim que o Render marca a execução do Cron Job como falha no
dashboard.
"""

import os
import sys

import httpx

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://cubemine-pix-api.onrender.com").rstrip("/")
ADMIN_SMOKE_TEST_TOKEN = os.environ.get("ADMIN_SMOKE_TEST_TOKEN")

REQUEST_TIMEOUT = 120


def main() -> None:
    if not ADMIN_SMOKE_TEST_TOKEN:
        print("ADMIN_SMOKE_TEST_TOKEN não configurado -- não dá pra chamar o endpoint admin.")
        sys.exit(1)

    response = httpx.get(
        f"{PUBLIC_BASE_URL}/admin/run-monthly-ranking-payout",
        headers={"X-Admin-Token": ADMIN_SMOKE_TEST_TOKEN},
        timeout=REQUEST_TIMEOUT,
    )
    print(f"GET /admin/run-monthly-ranking-payout -> {response.status_code} {response.text}")

    if response.status_code != 200:
        sys.exit(1)

    body = response.json()
    if not body.get("ok"):
        print(f"Job reportou falha: {body.get('error')}")
        sys.exit(1)

    print(
        f"ranking payout do mês {body.get('month')}: "
        f"{len(body.get('credited', []))} creditados, "
        f"{len(body.get('already_paid', []))} já pagos antes, "
        f"{len(body.get('insufficient_fund', []))} pulados por falta de saldo"
    )


if __name__ == "__main__":
    main()
