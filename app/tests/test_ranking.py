from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.models.reward_fund import SINGLETON_ID as FUND_SINGLETON_ID
from app.models.reward_fund import RewardFund
from app.models.user import User
from app.modules.levels.service import WEEKLY_MISSION_XP_BONUS
from app.modules.ranking.service import (
    MONTHLY_PAYOUT_SCALE,
    region_code_for,
    region_label_for,
    run_monthly_ranking_payout,
)
from app.modules.wallet.service import create_ledger_entry


def _fake_verify(uid: str, email: str):
    def _verify(id_token: str) -> dict:
        if id_token != "valid-token":
            raise firebase.InvalidFirebaseTokenError("bad token")
        return {"uid": uid, "email": email}

    return _verify


def _auth_header(token: str = "valid-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_user(client: TestClient, monkeypatch, uid: str, email: str) -> int:
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify(uid, email))
    response = client.post("/auth/register", json={}, headers=_auth_header())
    assert response.status_code == 201
    return response.json()["id"]


def _create_user(uid: str, email: str) -> int:
    """Cria o usuário direto no banco, sem passar por POST /auth/register --
    usado quando um teste precisa de muitos usuários (ex: Top 10 mensal com
    12 candidatos) e esbarraria no rate limit de registro (5/hora por IP)
    se passasse pelo endpoint de verdade."""
    db = SessionLocal()
    try:
        user = User(firebase_uid=uid, email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _set_user_geo(user_id: int, country_code: str | None, state_code: str | None = None, nickname: str | None = None) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        user.country_code = country_code
        user.state_code = state_code
        if nickname is not None:
            user.nickname = nickname
        db.commit()
    finally:
        db.close()


def _credit_reward(user_id: int, amount: Decimal, reference_id: str, created_at: datetime | None = None) -> None:
    db = SessionLocal()
    try:
        entry = create_ledger_entry(db, user_id=user_id, type=LedgerEntryType.REWARD, amount=amount, reference_id=reference_id)
        if created_at is not None:
            entry.created_at = created_at
        db.commit()
    finally:
        db.close()


def _top_up_reward_fund(amount: Decimal) -> None:
    db = SessionLocal()
    try:
        fund = db.query(RewardFund).filter(RewardFund.id == FUND_SINGLETON_ID).first()
        fund.balance += amount
        fund.total_in += amount
        db.commit()
    finally:
        db.close()


def _set_weekly_missions_completed(user_id: int, count: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        user.weekly_missions_completed = count
        db.commit()
    finally:
        db.close()


def _bonus_entries(user_id: int) -> list[LedgerEntry]:
    db = SessionLocal()
    try:
        return (
            db.query(LedgerEntry)
            .filter(LedgerEntry.user_id == user_id, LedgerEntry.type == LedgerEntryType.BONUS)
            .all()
        )
    finally:
        db.close()


# --- region_code_for / region_label_for -----------------------------------


def test_region_code_for_brazilian_user_uses_state():
    user = User(firebase_uid="x", email="x@example.com", country_code="BR", state_code="SP")
    assert region_code_for(user) == "BR-SP"
    assert region_label_for("BR-SP") == "São Paulo"


def test_region_code_for_brazilian_user_without_state_is_none():
    # Decisão confirmada: sem ranking regional por país -- um brasileiro
    # cujo estado ainda não foi detectado fica de fora do regional (mas
    # continua valendo no geral), em vez de cair num balde "BR" genérico.
    user = User(firebase_uid="x", email="x@example.com", country_code="BR", state_code=None)
    assert region_code_for(user) is None


def test_region_code_for_foreign_user_is_none():
    # Sem ranking por país pra quem está fora do Brasil (decisão
    # confirmada: app é majoritariamente Brasil/Pix/BRL por ora).
    user = User(firebase_uid="x", email="x@example.com", country_code="US", state_code="CA")
    assert region_code_for(user) is None


def test_region_code_for_undetected_location_is_none():
    user = User(firebase_uid="x", email="x@example.com", country_code=None, state_code=None)
    assert region_code_for(user) is None


def test_region_code_for_brazilian_state_does_not_collide_with_a_same_named_foreign_country():
    # "TO" é Tocantins (UF) E o código ISO de Tonga -- sem ranking regional
    # por país (ver test_region_code_for_foreign_user_is_none), um usuário
    # de Tonga nunca teria region_code de qualquer forma, mas o prefixo
    # "BR-" também garante que os dois nunca colidiriam se essa decisão
    # mudar no futuro.
    tocantins_user = User(firebase_uid="a", email="a@example.com", country_code="BR", state_code="TO")
    tonga_user = User(firebase_uid="b", email="b@example.com", country_code="TO", state_code=None)
    assert region_code_for(tocantins_user) == "BR-TO"
    assert region_code_for(tonga_user) is None


# --- GET /ranking -----------------------------------------------------------


def test_general_ranking_orders_by_lifetime_reward_total(client: TestClient, monkeypatch):
    user_a = _register_user(client, monkeypatch, "uid-rank-a", "rank-a@example.com")
    user_b = _register_user(client, monkeypatch, "uid-rank-b", "rank-b@example.com")
    user_c = _register_user(client, monkeypatch, "uid-rank-c", "rank-c@example.com")

    _credit_reward(user_a, Decimal("5.00"), "a-1")
    _credit_reward(user_b, Decimal("15.00"), "b-1")
    _credit_reward(user_c, Decimal("10.00"), "c-1")

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-rank-a", "rank-a@example.com"))
    response = client.get("/ranking", headers=_auth_header())
    assert response.status_code == 200
    general = response.json()["general"]
    assert [entry["user_id"] for entry in general["top"]] == [user_b, user_c, user_a]
    assert [entry["rank"] for entry in general["top"]] == [1, 2, 3]


def test_withdrawal_does_not_lower_ranking_position(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-rank-withdraw", "rank-withdraw@example.com")
    _credit_reward(user_id, Decimal("20.00"), "reward-1")

    db = SessionLocal()
    try:
        create_ledger_entry(db, user_id=user_id, type=LedgerEntryType.WITHDRAWAL, amount=Decimal("-15.00"), reference_id="w-1")
        db.commit()
    finally:
        db.close()

    response = client.get("/ranking", headers=_auth_header())
    body = response.json()
    assert Decimal(str(body["general"]["my_total"])) == Decimal("20.00")


def test_my_rank_and_display_name_fallback_when_no_nickname(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-rank-nick", "rank-nick@example.com")
    _credit_reward(user_id, Decimal("1.00"), "n-1")

    response = client.get("/ranking", headers=_auth_header())
    body = response.json()
    assert body["general"]["my_rank"] == 1
    assert body["general"]["top"][0]["display_name"] == f"Minerador #{user_id}"


def test_display_name_uses_nickname_once_set(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-rank-nick2", "rank-nick2@example.com")
    _credit_reward(user_id, Decimal("1.00"), "n-2")
    client.patch("/auth/nickname", json={"nickname": "MineradorTop"}, headers=_auth_header())

    response = client.get("/ranking", headers=_auth_header())
    assert response.json()["general"]["top"][0]["display_name"] == "MineradorTop"


def test_regional_ranking_only_includes_users_from_the_same_region(client: TestClient, monkeypatch):
    user_sp = _register_user(client, monkeypatch, "uid-rank-sp", "rank-sp@example.com")
    user_sp_2 = _register_user(client, monkeypatch, "uid-rank-sp2", "rank-sp2@example.com")
    user_rj = _register_user(client, monkeypatch, "uid-rank-rj", "rank-rj@example.com")

    _set_user_geo(user_sp, "BR", "SP")
    _set_user_geo(user_sp_2, "BR", "SP")
    _set_user_geo(user_rj, "BR", "RJ")

    _credit_reward(user_sp, Decimal("3.00"), "sp-1")
    _credit_reward(user_sp_2, Decimal("7.00"), "sp2-1")
    _credit_reward(user_rj, Decimal("100.00"), "rj-1")

    # Login de novo para o user_sp (registro já loga, mas o UID muda por
    # usuário -- refaz explicitamente pra garantir o token certo).
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-rank-sp", "rank-sp@example.com"))
    response = client.get("/ranking", headers=_auth_header())
    body = response.json()
    assert body["regional"]["region_code"] == "BR-SP"
    assert body["regional"]["region_label"] == "São Paulo"
    assert {entry["user_id"] for entry in body["regional"]["top"]} == {user_sp, user_sp_2}
    assert user_rj not in {entry["user_id"] for entry in body["regional"]["top"]}


def test_ranking_regional_is_none_when_location_never_detected(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-rank-nogeo", "rank-nogeo@example.com")
    _credit_reward(user_id, Decimal("1.00"), "nogeo-1")

    response = client.get("/ranking", headers=_auth_header())
    assert response.json()["regional"] is None


def test_ranking_requires_auth(client: TestClient):
    response = client.get("/ranking")
    assert response.status_code == 401


# --- PATCH /auth/nickname ---------------------------------------------------


def test_update_nickname_success(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-nick-ok", "nick-ok@example.com")
    response = client.patch("/auth/nickname", json={"nickname": "Foguete Roxo"}, headers=_auth_header())
    assert response.status_code == 200
    assert response.json()["nickname"] == "Foguete Roxo"


def test_update_nickname_rejects_too_short(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-nick-short", "nick-short@example.com")
    response = client.patch("/auth/nickname", json={"nickname": "ab"}, headers=_auth_header())
    assert response.status_code == 422


def test_update_nickname_rejects_disallowed_characters(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-nick-bad", "nick-bad@example.com")
    response = client.patch("/auth/nickname", json={"nickname": "<script>"}, headers=_auth_header())
    assert response.status_code == 422


# --- pagamento mensal do ranking --------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_monthly_payout(for_month):
    db = SessionLocal()
    try:
        return run_monthly_ranking_payout(db, for_month=for_month)
    finally:
        db.close()


def test_monthly_payout_credits_top10_by_scale_and_debits_reward_fund(client: TestClient, monkeypatch):
    _top_up_reward_fund(Decimal("100.00"))
    user_ids = [_create_user(f"uid-payout-{i}", f"payout-{i}@example.com") for i in range(12)]
    # Créditos DENTRO do mês corrente (janela padrão de run_monthly_ranking_payout
    # é o mês ANTERIOR -- por isso passamos for_month explicitamente pro mês
    # corrente, exercitando o parâmetro em vez de depender da data real).
    this_month = _now().date().replace(day=1)
    for i, user_id in enumerate(user_ids):
        _credit_reward(user_id, Decimal(str(12 - i)), f"payout-{i}-1", created_at=_now())

    result = _run_monthly_payout(this_month)
    assert len(result["credited"]) == 10  # só os 12 usuários, top 10 pagos
    assert len(result["insufficient_fund"]) == 0

    for position, entry in enumerate(sorted(result["credited"], key=lambda e: e["position"]), start=1):
        assert entry["scope"] == "geral"
        assert Decimal(entry["amount"]) == MONTHLY_PAYOUT_SCALE[position - 1]

    first_place_user = user_ids[0]  # maior total (12.00)
    bonuses = _bonus_entries(first_place_user)
    assert len(bonuses) == 1
    assert bonuses[0].amount == Decimal("1.00")

    eleventh_place_user = user_ids[10]
    assert _bonus_entries(eleventh_place_user) == []


def test_monthly_payout_is_idempotent_across_repeated_runs(monkeypatch, client: TestClient):
    _top_up_reward_fund(Decimal("100.00"))
    user_id = _register_user(client, monkeypatch, "uid-payout-idem", "payout-idem@example.com")
    this_month = _now().date().replace(day=1)
    _credit_reward(user_id, Decimal("5.00"), "idem-1", created_at=_now())

    first = _run_monthly_payout(this_month)
    second = _run_monthly_payout(this_month)

    assert len(first["credited"]) == 1
    assert len(second["credited"]) == 0
    assert len(second["already_paid"]) == 1

    assert len(_bonus_entries(user_id)) == 1  # nunca pago em dobro


def test_monthly_payout_stacks_general_and_regional_prizes_for_the_same_user(client: TestClient, monkeypatch):
    _top_up_reward_fund(Decimal("100.00"))
    user_id = _register_user(client, monkeypatch, "uid-payout-stack", "payout-stack@example.com")
    _set_user_geo(user_id, "BR", "SP")
    this_month = _now().date().replace(day=1)
    _credit_reward(user_id, Decimal("50.00"), "stack-1", created_at=_now())

    result = _run_monthly_payout(this_month)

    scopes = {entry["scope"] for entry in result["credited"]}
    assert "geral" in scopes
    assert "regional-BR-SP" in scopes
    assert len(_bonus_entries(user_id)) == 2  # ganhou os dois prêmios, empilhados
    total_bonus = sum((entry.amount for entry in _bonus_entries(user_id)), Decimal("0"))
    assert total_bonus == Decimal("2.00")  # R$1,00 (1o geral) + R$1,00 (1o regional)


def test_monthly_payout_only_pays_positions_the_fund_can_afford(client: TestClient, monkeypatch):
    # Fundo só dá pra pagar até 90% dele em qualquer débito (REWARD_FUND_SAFETY_MARGIN);
    # com um saldo minúsculo, nenhum vencedor deveria ser pago, mas o job não
    # deve lançar exceção -- só reportar os pulados.
    _top_up_reward_fund(Decimal("0.05"))
    user_id = _register_user(client, monkeypatch, "uid-payout-poor", "payout-poor@example.com")
    this_month = _now().date().replace(day=1)
    _credit_reward(user_id, Decimal("5.00"), "poor-1", created_at=_now())

    result = _run_monthly_payout(this_month)
    assert len(result["insufficient_fund"]) >= 1
    assert _bonus_entries(user_id) == []


def test_admin_run_monthly_ranking_payout_endpoint(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "test-admin-token")
    _top_up_reward_fund(Decimal("100.00"))
    user_id = _register_user(client, monkeypatch, "uid-payout-admin", "payout-admin@example.com")
    _credit_reward(user_id, Decimal("5.00"), "admin-1", created_at=_now())

    response = client.get("/admin/run-monthly-ranking-payout", headers={"X-Admin-Token": "test-admin-token"})
    assert response.status_code == 200
    assert response.json()["ok"] is True


# --- GET /ranking -- escopo by_level (XP/Nível, seção "Níveis") -----------


def test_by_level_ranks_by_xp_not_by_money(client: TestClient, monkeypatch):
    """Decisão de design: XP inclui o bônus fixo de missão semanal, que não
    é dinheiro -- então a ordem por XP pode divergir da ordem por dinheiro
    (ranking geral). Aqui, user_less_money tem menos dinheiro mas mais
    missões completadas, e sai na frente no ranking por nível."""
    user_more_money = _register_user(client, monkeypatch, "uid-level-money", "level-money@example.com")
    user_less_money = _register_user(client, monkeypatch, "uid-level-missions", "level-missions@example.com")

    _credit_reward(user_more_money, Decimal("10.00"), "money-1")  # 1000 XP, 0 missões
    _credit_reward(user_less_money, Decimal("5.00"), "missions-1")  # 500 XP
    _set_weekly_missions_completed(user_less_money, 10)  # + 10*100 = 1000 XP => total 1500 XP

    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-level-money", "level-money@example.com"))
    response = client.get("/ranking", headers=_auth_header())
    assert response.status_code == 200
    top = response.json()["by_level"]["top"]

    assert [entry["user_id"] for entry in top[:2]] == [user_less_money, user_more_money]
    assert top[0]["xp"] == 1500
    assert top[1]["xp"] == 1000


def test_by_level_my_xp_and_level_present_even_with_zero_reward(client: TestClient, monkeypatch):
    """Ao contrário de general/regional (que ficam com my_rank=None e
    my_total=0 pra quem nunca coletou nada), todo usuário TEM um nível --
    my_level/my_xp nunca ficam ausentes, mesmo pra quem nunca minerou."""
    _register_user(client, monkeypatch, "uid-level-new", "level-new@example.com")

    response = client.get("/ranking", headers=_auth_header())
    assert response.status_code == 200
    by_level = response.json()["by_level"]
    assert by_level["my_level"] == 1
    assert by_level["my_xp"] == 0
    assert by_level["my_rank"] is None


def test_by_level_reflects_mission_bonus_xp_for_the_current_user(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-level-mine", "level-mine@example.com")
    _credit_reward(user_id, Decimal("2.00"), "mine-1")  # 200 XP
    _set_weekly_missions_completed(user_id, 3)  # + 3*100 = 300 XP

    response = client.get("/ranking", headers=_auth_header())
    assert response.status_code == 200
    by_level = response.json()["by_level"]
    assert by_level["my_xp"] == 200 + 3 * WEEKLY_MISSION_XP_BONUS
    assert by_level["my_rank"] == 1
