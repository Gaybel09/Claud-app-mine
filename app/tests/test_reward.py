from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.core.admob import AdMobApiError, AdMobConfigurationError, admob_client
from app.db.session import SessionLocal
from app.models.ad_view import AdView, AdViewStatus
from app.models.cube import Cube, CubeType
from app.models.ledger_entry import LedgerEntry
from app.models.mining_session import MiningSession
from app.models.reward_config import SINGLETON_ID, RewardConfig
from app.models.reward_fund import SINGLETON_ID as FUND_SINGLETON_ID
from app.models.reward_fund import RewardFund
from app.modules.mining.service import collect_mining_session
from app.modules.reward.service import (
    MAX_REWARD,
    MIN_REWARD,
    compute_value_per_session,
    update_reward_config_from_admob,
)


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


def _get_reward_config() -> RewardConfig:
    db = SessionLocal()
    try:
        return db.query(RewardConfig).filter(RewardConfig.id == SINGLETON_ID).first()
    finally:
        db.close()


# --- cálculo do valor a partir do eCPM (item 6 do pedido) -----------------


def test_compute_value_per_session_applies_margin_and_rounds_down():
    # eCPM 20.00, margem 0.5 -> (20.00 * 0.5) / 1000 = 0.01 -- já no piso
    # (MIN_REWARD), então o teste abaixo usa um eCPM maior para exercitar o
    # cálculo "livre" (sem bater em nenhum dos limites de segurança).
    avg_ecpm = Decimal("600.00")  # (600 * 0.5) / 1000 = 0.30
    assert compute_value_per_session(avg_ecpm) == Decimal("0.30")


def test_compute_value_per_session_rounds_down_not_to_nearest():
    # (633 * 0.5) / 1000 = 0.3165 -- arredonda para baixo (0.31), nunca para
    # cima (0.32), a favor da margem de segurança do fundo.
    avg_ecpm = Decimal("633.00")
    assert compute_value_per_session(avg_ecpm) == Decimal("0.31")


def test_compute_value_per_session_clamps_to_min_reward():
    # eCPM muito baixo (ou zero) não pode gerar um valor por sessão abaixo
    # do piso de segurança.
    assert compute_value_per_session(Decimal("0.00")) == MIN_REWARD
    assert compute_value_per_session(Decimal("1.00")) == MIN_REWARD


def test_compute_value_per_session_clamps_to_max_reward():
    # eCPM anômalo/corrompido não pode gerar um valor por sessão acima do
    # teto de segurança, mesmo que o cálculo bruto desse um valor maior.
    assert compute_value_per_session(Decimal("100000.00")) == MAX_REWARD


# --- worker atualizando a config (item 3 do pedido) -----------------------


def test_update_reward_config_from_admob_updates_value_and_ecpm(monkeypatch):
    monkeypatch.setattr(admob_client, "get_average_ecpm", lambda target_date, ad_unit_id=None: Decimal("600.00"))

    db = SessionLocal()
    try:
        config = update_reward_config_from_admob(db, for_date=date(2026, 7, 24))
    finally:
        db.close()

    assert config.value_per_session == Decimal("0.30")
    assert config.avg_ecpm == Decimal("600.00")

    persisted = _get_reward_config()
    assert persisted.value_per_session == Decimal("0.30")
    assert persisted.avg_ecpm == Decimal("600.00")


def test_update_reward_config_from_admob_uses_yesterday_by_default(monkeypatch):
    captured_dates = []

    def _fake_get_average_ecpm(target_date, ad_unit_id=None):
        captured_dates.append(target_date)
        return Decimal("600.00")

    monkeypatch.setattr(admob_client, "get_average_ecpm", _fake_get_average_ecpm)

    db = SessionLocal()
    try:
        update_reward_config_from_admob(db)
    finally:
        db.close()

    expected = datetime.now(timezone.utc).date() - timedelta(days=1)
    assert captured_dates == [expected]


def test_update_reward_config_from_admob_keeps_value_when_no_data(monkeypatch):
    monkeypatch.setattr(admob_client, "get_average_ecpm", lambda target_date, ad_unit_id=None: None)

    before = _get_reward_config()

    db = SessionLocal()
    try:
        config = update_reward_config_from_admob(db, for_date=date(2026, 7, 24))
    finally:
        db.close()

    assert config.value_per_session == before.value_per_session
    assert config.avg_ecpm == before.avg_ecpm


def test_update_reward_config_from_admob_propagates_configuration_error(monkeypatch):
    def _raise(target_date, ad_unit_id=None):
        raise AdMobConfigurationError("not configured")

    monkeypatch.setattr(admob_client, "get_average_ecpm", _raise)

    db = SessionLocal()
    try:
        try:
            update_reward_config_from_admob(db, for_date=date(2026, 7, 24))
            assert False, "expected AdMobConfigurationError"
        except AdMobConfigurationError:
            pass
    finally:
        db.close()


def test_admin_update_reward_config_endpoint_reports_configuration_error(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "test-admin-token")

    def _raise(target_date, ad_unit_id=None):
        raise AdMobConfigurationError("ADMOB_CLIENT_ID/... not configured")

    monkeypatch.setattr(admob_client, "get_average_ecpm", _raise)

    response = client.get("/admin/update-reward-config", headers={"X-Admin-Token": "test-admin-token"})
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_admin_update_reward_config_endpoint_updates_config(client: TestClient, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ADMIN_SMOKE_TEST_TOKEN", "test-admin-token")
    monkeypatch.setattr(admob_client, "get_average_ecpm", lambda target_date, ad_unit_id=None: Decimal("600.00"))

    response = client.get("/admin/update-reward-config", headers={"X-Admin-Token": "test-admin-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["value_per_session"] == "0.30"
    assert body["avg_ecpm"] == "600.00"


# --- GET /reward/current (item 4 do pedido) -------------------------------


def test_reward_current_returns_seeded_default(client: TestClient):
    response = client.get("/reward/current")
    assert response.status_code == 200
    body = response.json()
    assert Decimal(str(body["value_per_session"])) == Decimal("0.30")
    assert body["avg_ecpm"] is None


def test_reward_current_reflects_worker_update(client: TestClient, monkeypatch):
    monkeypatch.setattr(admob_client, "get_average_ecpm", lambda target_date, ad_unit_id=None: Decimal("900.00"))
    db = SessionLocal()
    try:
        update_reward_config_from_admob(db, for_date=date(2026, 7, 24))
    finally:
        db.close()

    response = client.get("/reward/current")
    assert response.status_code == 200
    body = response.json()
    assert Decimal(str(body["value_per_session"])) == Decimal("0.45")
    assert Decimal(str(body["avg_ecpm"])) == Decimal("900.00")


def test_reward_current_requires_no_auth(client: TestClient):
    # Rota pública -- nenhum header de autenticação.
    response = client.get("/reward/current")
    assert response.status_code == 200


# --- collect_mining_session credita o valor vigente (item 5 do pedido) ----


def _create_cube(user_id: int) -> int:
    db = SessionLocal()
    try:
        cube = Cube(user_id=user_id, type=CubeType.COMUM, speed=Decimal("1.00"), bonus_chance=Decimal("0.05"))
        db.add(cube)
        db.commit()
        db.refresh(cube)
        return cube.id
    finally:
        db.close()


def _create_ad_view(user_id: int, status: str) -> int:
    db = SessionLocal()
    try:
        ad_view = AdView(user_id=user_id, ad_network="admob", status=status)
        db.add(ad_view)
        db.commit()
        db.refresh(ad_view)
        return ad_view.id
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


def _set_value_per_session(value: Decimal) -> None:
    db = SessionLocal()
    try:
        config = db.query(RewardConfig).filter(RewardConfig.id == SINGLETON_ID).first()
        config.value_per_session = value
        db.commit()
    finally:
        db.close()


def test_collect_mining_session_credits_current_reward_config_value(client: TestClient, monkeypatch):
    _set_value_per_session(Decimal("0.77"))
    _top_up_reward_fund(Decimal("100.00"))

    user_id = _register_user(client, monkeypatch, "uid-reward-config", "reward-config@example.com")
    cube_id = _create_cube(user_id)
    ad_view_id = _create_ad_view(user_id, AdViewStatus.CONFIRMED)

    start_response = client.post(
        "/mining/start", json={"cube_id": cube_id, "ad_view_id": ad_view_id}, headers=_auth_header()
    )
    assert start_response.status_code == 201
    session_id = start_response.json()["id"]

    db = SessionLocal()
    try:
        session = db.query(MiningSession).filter(MiningSession.id == session_id).first()
        session.ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    collect_response = client.post(
        "/mining/collect",
        json={"session_id": session_id},
        headers={**_auth_header(), "Idempotency-Key": "collect-reward-config-1"},
    )
    assert collect_response.status_code == 200
    assert Decimal(str(collect_response.json()["reward_amount"])) == Decimal("0.77")

    db = SessionLocal()
    try:
        entry = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.user_id == user_id, LedgerEntry.reference_id == str(session_id))
            .first()
        )
    finally:
        db.close()
    assert entry is not None
    assert entry.amount == Decimal("0.77")


def test_collect_mining_session_changes_amount_when_reward_config_changes(monkeypatch):
    """Duas sessões coletadas com valores de reward_config diferentes devem
    creditar valores diferentes -- prova de que o valor não é mais fixo."""
    db = SessionLocal()
    try:
        from app.models.user import User

        user = User(firebase_uid="uid-varies", email="varies@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        fund = db.query(RewardFund).filter(RewardFund.id == FUND_SINGLETON_ID).first()
        fund.balance += Decimal("100.00")
        fund.total_in += Decimal("100.00")
        db.commit()

        cube = Cube(user_id=user_id, type=CubeType.COMUM, speed=Decimal("1.00"), bonus_chance=Decimal("0.05"))
        db.add(cube)
        db.commit()
        db.refresh(cube)

        def _new_session(value_per_session: Decimal) -> Decimal:
            config = db.query(RewardConfig).filter(RewardConfig.id == SINGLETON_ID).first()
            config.value_per_session = value_per_session
            db.commit()

            ad_view = AdView(user_id=user_id, ad_network="admob", status=AdViewStatus.CONFIRMED)
            db.add(ad_view)
            db.commit()
            db.refresh(ad_view)

            session = MiningSession(
                user_id=user_id,
                cube_id=cube.id,
                ad_view_id=ad_view.id,
                started_at=datetime.now(timezone.utc) - timedelta(hours=3),
                ends_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
            db.add(session)
            db.commit()
            db.refresh(session)

            _, reward_amount = collect_mining_session(db, user_id, session.id)
            return reward_amount

        first_amount = _new_session(Decimal("0.20"))
        second_amount = _new_session(Decimal("0.55"))

        assert first_amount == Decimal("0.20")
        assert second_amount == Decimal("0.55")
        assert first_amount != second_amount
    finally:
        db.close()
