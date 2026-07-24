#!/usr/bin/env python3
"""Smoke test manual do fluxo completo cadastro -> ... -> saque Pix, contra
uma API real (por padrão, a de produção no Render) e o sandbox da Efí.

NÃO é um teste automatizado (não roda em CI, não usa pytest) -- é uma
ferramenta pra rodar sob demanda quando você quiser validar o fluxo de
verdade contra o ambiente real. Cria um usuário de teste real no seu
projeto Firebase e dispara um envio Pix real (para o sandbox da Efí) a
cada execução.

Uso básico:
    pip install requests
    export FIREBASE_WEB_API_KEY="AIzaSy..."   # o apiKey do firebase_options.dart
    export TEST_PIX_KEY="mesma chave de EFI_PAYER_PIX_KEY, ou outra de teste"
    python3 scripts/manual_pix_smoke_test.py

Variáveis de ambiente:
    API_BASE_URL        default: https://cubemine-pix-api.onrender.com
    FIREBASE_WEB_API_KEY  obrigatória -- cria o usuário de teste via REST
                          do Firebase Auth (Identity Toolkit), sem precisar
                          do Admin SDK.
    TEST_PIX_KEY         obrigatória -- chave Pix de destino do saque.
    WITHDRAW_AMOUNT      opcional -- default: a recompensa coletada.
    PROD_DATABASE_URL    opcional -- se setada, o script conecta direto no
                          Postgres (via SQLAlchemy) pra adiantar o ends_at
                          da sessão de mineração, do mesmo jeito que os
                          testes de integração fazem localmente. SEM essa
                          variável, o script espera o tempo real (2h) até
                          ends_at -- mais lento, mas não precisa de nenhum
                          acesso além da própria API pública.

                          Atenção: isso conecta direto no banco de PRODUÇÃO
                          e faz um UPDATE fora de qualquer endpoint da API.
                          Só forneça essa URL se você tiver certeza do que
                          está fazendo.
"""

import os
import sys
import time
import uuid
from datetime import datetime, timezone

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "https://cubemine-pix-api.onrender.com").rstrip("/")
FIREBASE_WEB_API_KEY = os.environ.get("FIREBASE_WEB_API_KEY")
TEST_PIX_KEY = os.environ.get("TEST_PIX_KEY")
WITHDRAW_AMOUNT = os.environ.get("WITHDRAW_AMOUNT")
PROD_DATABASE_URL = os.environ.get("PROD_DATABASE_URL")

REQUEST_TIMEOUT = 30


def step(n, title):
    print(f"\n=== Passo {n}: {title} ===", flush=True)


def fail(message):
    print(f"\nFALHOU: {message}", flush=True)
    sys.exit(1)


def firebase_sign_up(email: str, password: str) -> str:
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_WEB_API_KEY}"
    response = requests.post(
        url, json={"email": email, "password": password, "returnSecureToken": True}, timeout=REQUEST_TIMEOUT
    )
    if response.status_code != 200:
        fail(f"Firebase sign-up falhou: {response.status_code} {response.text}")
    return response.json()["idToken"]


def force_ends_at_now(session_id: int) -> None:
    """Empurra mining_sessions.ends_at pro passado, conectando direto no
    Postgres de produção -- só roda se PROD_DATABASE_URL foi fornecida."""
    from sqlalchemy import create_engine, text

    engine = create_engine(PROD_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE mining_sessions SET ends_at = now() - interval '1 second' WHERE id = :id"),
            {"id": session_id},
        )
    engine.dispose()


def main() -> None:
    if not FIREBASE_WEB_API_KEY:
        fail("Defina FIREBASE_WEB_API_KEY (o apiKey em mobile/lib/firebase_options.dart)")
    if not TEST_PIX_KEY:
        fail("Defina TEST_PIX_KEY (uma chave Pix de teste para o saque, ex: a mesma de EFI_PAYER_PIX_KEY)")

    run_id = uuid.uuid4().hex[:8]
    email = f"pix-smoke-test-{run_id}@example.com"
    password = f"Sm0keTest!{run_id}"

    print(f"API_BASE_URL={API_BASE_URL}")
    print(f"Usuário de teste a ser criado: {email}")

    step(0, "Saúde da API e da autenticação com a Efí")
    health = requests.get(f"{API_BASE_URL}/health", timeout=REQUEST_TIMEOUT)
    print(f"GET /health -> {health.status_code} {health.text}")
    if health.status_code != 200:
        fail("API não está saudável -- abortando antes de criar dados de teste")

    efi_health = requests.get(f"{API_BASE_URL}/pix/health", timeout=REQUEST_TIMEOUT)
    print(f"GET /pix/health -> {efi_health.status_code} {efi_health.text}")
    if efi_health.status_code != 200:
        print(
            "AVISO: /pix/health não retornou 200 -- a autenticação com a Efí "
            "pode estar com problema. Continuando mesmo assim para ver o erro "
            "real no POST /pix/withdraw mais adiante."
        )

    step(1, "Registrar usuário de teste (Firebase + backend)")
    id_token = firebase_sign_up(email, password)
    headers = {"Authorization": f"Bearer {id_token}"}
    register = requests.post(
        f"{API_BASE_URL}/auth/register", json={"pix_key": TEST_PIX_KEY}, headers=headers, timeout=REQUEST_TIMEOUT
    )
    print(f"POST /auth/register -> {register.status_code} {register.text}")
    if register.status_code != 201:
        fail("Registro falhou")
    user = register.json()
    print(f"Usuário criado: id={user['id']} email={user['email']}")

    step(2, "Confirmar o cubo inicial")
    cubes = requests.get(f"{API_BASE_URL}/cubes/me", headers=headers, timeout=REQUEST_TIMEOUT)
    print(f"GET /cubes/me -> {cubes.status_code} {cubes.text}")
    if cubes.status_code != 200 or not cubes.json():
        fail("Nenhum cubo encontrado para o novo usuário")
    cube_id = cubes.json()[0]["id"]
    print(f"cube_id={cube_id} (type={cubes.json()[0]['type']})")

    step(3, "Assistir anúncio e confirmar via callback")
    watch = requests.post(
        f"{API_BASE_URL}/ads/watch", json={"ad_network": "manual-smoke-test"}, headers=headers, timeout=REQUEST_TIMEOUT
    )
    print(f"POST /ads/watch -> {watch.status_code} {watch.text}")
    if watch.status_code != 201:
        fail("POST /ads/watch falhou")
    ad_view_id = watch.json()["id"]

    callback = requests.post(
        f"{API_BASE_URL}/ads/callback",
        json={"ad_view_id": ad_view_id, "user_id": user["id"], "status": "confirmed"},
        timeout=REQUEST_TIMEOUT,
    )
    print(f"POST /ads/callback -> {callback.status_code} {callback.text}")
    if callback.status_code != 200:
        fail("POST /ads/callback falhou")

    step(4, "Iniciar mineração e coletar a recompensa")
    start = requests.post(
        f"{API_BASE_URL}/mining/start",
        json={"cube_id": cube_id, "ad_view_id": ad_view_id},
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    print(f"POST /mining/start -> {start.status_code} {start.text}")
    if start.status_code != 201:
        fail("POST /mining/start falhou")
    session = start.json()
    session_id = session["id"]
    ends_at = datetime.fromisoformat(session["ends_at"].replace("Z", "+00:00"))

    if PROD_DATABASE_URL:
        print(f"PROD_DATABASE_URL fornecida -- adiantando ends_at da sessão {session_id} direto no banco.")
        force_ends_at_now(session_id)
    else:
        wait_seconds = max(0.0, (ends_at - datetime.now(timezone.utc)).total_seconds()) + 5
        print(
            f"Sessão {session_id} termina em {ends_at.isoformat()}. Sem "
            f"PROD_DATABASE_URL, vou esperar o tempo real: {wait_seconds:.0f}s "
            "(~2h). Defina PROD_DATABASE_URL para pular a espera."
        )
        time.sleep(wait_seconds)

    collect_idempotency_key = f"manual-smoke-collect-{run_id}"
    collect = requests.post(
        f"{API_BASE_URL}/mining/collect",
        json={"session_id": session_id},
        headers={**headers, "Idempotency-Key": collect_idempotency_key},
        timeout=REQUEST_TIMEOUT,
    )
    print(f"POST /mining/collect -> {collect.status_code} {collect.text}")
    if collect.status_code != 200:
        fail("POST /mining/collect falhou")
    reward_amount = collect.json()["reward_amount"]
    print(f"Recompensa coletada: R$ {reward_amount}")

    step(5, "Consultar saldo na wallet")
    balance = requests.get(f"{API_BASE_URL}/wallet/balance", headers=headers, timeout=REQUEST_TIMEOUT)
    print(f"GET /wallet/balance -> {balance.status_code} {balance.text}")
    if balance.status_code != 200:
        fail("GET /wallet/balance falhou")

    step(6, "Solicitar saque via Pix")
    withdraw_amount = WITHDRAW_AMOUNT or str(reward_amount)
    withdraw_idempotency_key = f"manual-smoke-withdraw-{run_id}"
    withdraw = requests.post(
        f"{API_BASE_URL}/pix/withdraw",
        json={"amount": withdraw_amount, "pix_key": TEST_PIX_KEY},
        headers={**headers, "Idempotency-Key": withdraw_idempotency_key},
        timeout=REQUEST_TIMEOUT,
    )
    print(f"POST /pix/withdraw -> {withdraw.status_code} {withdraw.text}")

    step(7, "Consultar GET /pix/withdrawals e reportar o status final")
    time.sleep(5)  # dá um tempo pro webhook/processamento assíncrono da Efí, se aplicável
    withdrawals = requests.get(f"{API_BASE_URL}/pix/withdrawals", headers=headers, timeout=REQUEST_TIMEOUT)
    print(f"GET /pix/withdrawals -> {withdrawals.status_code}")
    print(withdrawals.text)

    print("\n=== RESUMO ===")
    print(f"Usuário de teste: {email} (id={user['id']})")
    print(f"Cubo: {cube_id}")
    print(f"Sessão de mineração: {session_id}, recompensa: R$ {reward_amount}")
    print(f"Saque solicitado: R$ {withdraw_amount} para a chave {TEST_PIX_KEY}")
    if withdrawals.status_code == 200 and withdrawals.json():
        final_status = withdrawals.json()[0]["status"]
        print(f"Status final do saque (após ~5s): {final_status}")
        if final_status == "processing":
            print(
                "Ainda em 'processing' -- normal se o webhook da Efí ainda não "
                "chegou. Rode `curl -H 'Authorization: Bearer <id_token>' "
                f"{API_BASE_URL}/pix/withdrawals` de novo daqui a alguns "
                "minutos, ou espere o worker de reconciliação (a cada 5min, "
                "só age depois de 10min parado -- ver app/workers/tasks.py)."
            )
    else:
        print("Não foi possível obter o status final do saque.")


if __name__ == "__main__":
    main()
