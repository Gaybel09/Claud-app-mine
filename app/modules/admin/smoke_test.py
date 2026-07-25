"""Smoke test de diagnóstico do fluxo completo (seções 7 e 11): cadastro ->
cubo -> anúncio -> mineração -> saldo -> saque Pix, rodando dentro do
próprio processo do backend -- sem nenhuma chamada HTTP externa a si
mesmo, usando a mesma sessão de banco da requisição.

ATENÇÃO -- isto é só para diagnóstico manual, nunca para produção de
verdade (fora de sandbox):
  - Cria dados reais (usuário, cubo, sessão de mineração, ledger entries,
    withdrawal) a cada chamada. São sempre limpos ao final (sucesso ou
    falha), mas ainda assim é escrita real no banco de produção.
  - Dispara uma chamada REAL de envio de Pix para a Efí, sempre para
    EFI_SANDBOX_HOMOLOGATION_PIX_KEY (ver abaixo) -- em sandbox isso não
    move dinheiro de verdade, mas fora de sandbox seria uma transferência
    real (e essa chave de homologação não existiria/não bateria de
    verdade).
  - O endpoint GET /admin/smoke-test/pix que chama isto só deve ficar
    acessível enquanto ADMIN_SMOKE_TEST_TOKEN estiver configurado.
    REMOVA a rota (ou pare de configurar essa variável) antes de operar
    fora de sandbox.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ad_view import AdView, AdViewStatus
from app.models.cube import Cube, create_starter_cube
from app.models.ledger_entry import LedgerEntry
from app.models.mining_session import MiningSession
from app.models.reward_fund import SINGLETON_ID, RewardFund
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.modules.ads.service import apply_ad_callback
from app.modules.mining.service import collect_mining_session, start_mining_session
from app.modules.reward.service import MAX_REWARD
from app.modules.pix.service import create_withdrawal, list_user_withdrawals
from app.modules.wallet.service import compute_balance
from app.workers.tasks import reconcile_withdrawal

# Headroom temporário dado ao reward_fund só para o sorteio da recompensa (até
# MAX_REWARD) nunca falhar por falta de saldo, independente do saldo real do
# fundo em produção. É revertido ao valor exato de antes ao final (sucesso ou
# falha), igual à limpeza de usuário/cubo/etc feita em _cleanup.
SMOKE_TEST_FUND_HEADROOM = MAX_REWARD * 10

# Chave Pix oficial de homologação da Efí para testes de envio (Pix Out) em
# sandbox -- documentada em dev.efipay.com.br/docs/api-pix/
# envio-pagamento-pix ("Instruções para testes em Homologação"): só saques
# para EXATAMENTE essa chave são confirmados/rejeitados de verdade pela Efí
# em sandbox (valores entre R$0,01 e R$10,00, dentro da faixa de
# MIN_REWARD/MAX_REWARD, são confirmados via webhook). Qualquer outra
# chave -- mesmo uma chave real válida -- dá
# "chave_favorecido_nao_encontrada". É ESPECÍFICA DO SANDBOX DE
# HOMOLOGAÇÃO DA EFÍ: nunca deve ser usada em produção real, onde a
# pix_key do saque vem do usuário de verdade (ver POST /pix/withdraw,
# que nunca usa essa constante). Fixa aqui de propósito -- não vem de
# EFI_PAYER_PIX_KEY nem de nenhum outro parâmetro/configuração.
EFI_SANDBOX_HOMOLOGATION_PIX_KEY = "efipay@sejaefi.com.br"


def run_pix_smoke_test(db: Session, force_reconcile: bool = False) -> dict:
    """force_reconcile: roda reconcile_withdrawal (a mesma lógica do worker
    periódico pix.reconcile_pending_withdrawals) logo após pix_withdraw, em
    vez de esperar o agendamento do Celery Beat (a cada 5min) e o corte de
    RECONCILE_AFTER_MINUTES (10min) -- útil para confirmar que o fluxo
    funciona só com a reconciliação, sem depender do webhook receber
    corretamente (ex: mTLS de recebimento não viável no plano gratuito do
    Render)."""
    if not settings.EFI_PAYER_PIX_KEY:
        return {
            "run_id": None,
            "overall": "not_configured",
            "error": "EFI_PAYER_PIX_KEY is not configured -- nothing to test",
            "steps": {},
        }

    run_id = uuid.uuid4().hex[:8]
    steps: dict[str, dict] = {}
    state: dict = {}

    def _register():
        user = User(
            firebase_uid=f"smoke-test-{run_id}",
            email=f"smoke-test-{run_id}@example.com",
            pix_key=settings.EFI_PAYER_PIX_KEY,
        )
        db.add(user)
        db.flush()
        db.add(create_starter_cube(user.id))
        db.commit()
        db.refresh(user)
        state["user"] = user
        return {"user_id": user.id, "email": user.email}

    def _cube():
        cube = db.query(Cube).filter(Cube.user_id == state["user"].id).first()
        if cube is None:
            raise RuntimeError("no starter cube found")
        state["cube"] = cube
        return {"cube_id": cube.id, "type": cube.type}

    def _ads():
        ad_view = AdView(user_id=state["user"].id, ad_network="admin-smoke-test")
        db.add(ad_view)
        db.commit()
        db.refresh(ad_view)
        confirmed = apply_ad_callback(
            db, ad_view_id=ad_view.id, user_id=state["user"].id, status=AdViewStatus.CONFIRMED
        )
        if confirmed is None or confirmed.status != AdViewStatus.CONFIRMED:
            raise RuntimeError("failed to confirm ad_view")
        state["ad_view"] = confirmed
        return {"ad_view_id": confirmed.id, "status": confirmed.status}

    def _mining():
        session = start_mining_session(
            db, user_id=state["user"].id, cube_id=state["cube"].id, ad_view_id=state["ad_view"].id
        )
        # "Aguardar" o ciclo de 2h: mesma sessão de banco da requisição, sem
        # precisar de nenhuma credencial externa (ver módulo mining).
        session.ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        collected_session, reward_amount = collect_mining_session(
            db, user_id=state["user"].id, session_id=session.id
        )
        state["reward_amount"] = reward_amount
        return {"session_id": collected_session.id, "reward_amount": str(reward_amount)}

    def _wallet_balance():
        balance = compute_balance(db, state["user"].id)
        return {"balance": str(balance)}

    def _pix_withdraw():
        idempotency_key = f"admin-smoke-test-{run_id}"
        withdrawal, _ = create_withdrawal(
            db,
            user_id=state["user"].id,
            amount=state["reward_amount"],
            # Sempre a chave de homologação da Efí, nunca EFI_PAYER_PIX_KEY
            # nem qualquer outra configuração -- ver EFI_SANDBOX_HOMOLOGATION_PIX_KEY.
            pix_key=EFI_SANDBOX_HOMOLOGATION_PIX_KEY,
            idempotency_key=idempotency_key,
        )
        state["withdrawal"] = withdrawal
        return {
            "withdrawal_id": withdrawal.id,
            "status": withdrawal.status,
            "pix_key": withdrawal.pix_key,
            # idEnvio de verdade enviado à Efí (derivado de idempotency_key
            # -- ver app.core.efi.derive_id_envio), útil pra conferir no
            # painel da Efí qual envio corresponde a este smoke test.
            "efi_id_envio": withdrawal.efi_id_envio,
            # Motivo reportado pela Efí quando status == "failed" -- ver
            # Withdrawal.failure_reason. Só null quando não houve falha.
            "failure_reason": withdrawal.failure_reason,
        }

    def _pix_reconcile():
        withdrawal = state["withdrawal"]
        status_before = withdrawal.status
        reconcile_withdrawal(db, withdrawal)
        db.refresh(withdrawal)
        return {
            "status_before": status_before,
            "status_after": withdrawal.status,
            "failure_reason": withdrawal.failure_reason,
        }

    def _pix_withdrawals_list():
        withdrawals = list_user_withdrawals(db, state["user"].id)
        final = withdrawals[0] if withdrawals else None
        return {
            "count": len(withdrawals),
            "final_status": final.status if final else None,
            "final_failure_reason": final.failure_reason if final else None,
        }

    ordered_steps = [
        ("register", _register),
        ("cube", _cube),
        ("ads", _ads),
        ("mining", _mining),
        ("wallet_balance", _wallet_balance),
        ("pix_withdraw", _pix_withdraw),
    ]
    if force_reconcile:
        ordered_steps.append(("pix_reconcile", _pix_reconcile))
    ordered_steps.append(("pix_withdrawals_list", _pix_withdrawals_list))

    fund_snapshot = _grant_temporary_fund_headroom(db)
    try:
        for name, fn in ordered_steps:
            try:
                result = fn()
                steps[name] = {"ok": True, **(result or {})}
            except Exception as exc:
                steps[name] = {"ok": False, "error": str(exc)}
                break
    finally:
        user = state.get("user")
        _cleanup(db, user.id if user else None)
        _restore_fund(db, fund_snapshot)

    overall_ok = len(steps) == len(ordered_steps) and all(s["ok"] for s in steps.values())
    return {
        "run_id": run_id,
        "overall": "ok" if overall_ok else "failed",
        "steps": steps,
    }


def _grant_temporary_fund_headroom(db: Session) -> dict | None:
    """Dá um saldo extra temporário ao reward_fund para o passo de mineração
    nunca falhar por saldo insuficiente, guardando os valores originais para
    restaurar depois (ver _restore_fund)."""
    fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).with_for_update().first()
    if fund is None:
        return None
    snapshot = {"balance": fund.balance, "total_in": fund.total_in, "total_out": fund.total_out}
    fund.balance += SMOKE_TEST_FUND_HEADROOM
    fund.total_in += SMOKE_TEST_FUND_HEADROOM
    db.commit()
    return snapshot


def _restore_fund(db: Session, snapshot: dict | None) -> None:
    """Restaura o reward_fund ao estado exato de antes do smoke test, para
    o diagnóstico nunca alterar permanentemente o saldo real do fundo."""
    if snapshot is None:
        return
    db.rollback()
    fund = db.query(RewardFund).filter(RewardFund.id == SINGLETON_ID).with_for_update().first()
    if fund is None:
        return
    fund.balance = snapshot["balance"]
    fund.total_in = snapshot["total_in"]
    fund.total_out = snapshot["total_out"]
    db.commit()


def _cleanup(db: Session, user_id: int | None) -> None:
    """Apaga tudo que o smoke test criou para este user_id, para não deixar
    lixo de diagnóstico acumulando no banco a cada execução."""
    if user_id is None:
        return
    db.rollback()  # descarta qualquer transação em estado de erro antes de limpar
    db.query(LedgerEntry).filter(LedgerEntry.user_id == user_id).delete()
    db.query(Withdrawal).filter(Withdrawal.user_id == user_id).delete()
    db.query(MiningSession).filter(MiningSession.user_id == user_id).delete()
    db.query(AdView).filter(AdView.user_id == user_id).delete()
    db.query(Cube).filter(Cube.user_id == user_id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()
