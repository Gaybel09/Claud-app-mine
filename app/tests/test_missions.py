from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.models.ledger_entry import LedgerEntryType
from app.models.user import User
from app.modules.missions.service import (
    WEEKLY_MISSION_MULTIPLIER,
    WEEKLY_MISSION_MULTIPLIER_DURATION,
    WEEKLY_MISSION_TARGET,
    _week_window,
    get_weekly_mission_status,
    is_multiplier_active,
    maybe_activate_weekly_mission,
    weekly_collections_count,
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
    db = SessionLocal()
    try:
        user = User(firebase_uid=uid, email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def _get_user(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def _set_multiplier_until(user_id: int, until: datetime | None) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        user.weekly_mission_multiplier_until = until
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


# --- _week_window (corte segunda 00h BRT, não UTC) -------------------------


def test_week_window_starts_monday_midnight_brt_not_utc():
    # Terça 2026-08-04, 15h UTC (meio da tarde no Brasil) -- a semana em
    # que cai deveria começar segunda 2026-08-03 00h BRT == 03h UTC.
    tuesday_afternoon_utc = datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)
    start, end = _week_window(tuesday_afternoon_utc)
    assert start == datetime(2026, 8, 3, 3, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)


def test_week_window_sunday_night_utc_is_still_previous_week_in_brt():
    # Domingo 2026-08-09, 23h30 UTC == domingo 20h30 no horário de
    # Brasília -- ainda dentro da semana que começou segunda 2026-08-03,
    # não da semana seguinte (só vira segunda em BRT às 2026-08-10 03h UTC).
    # Se o corte fosse 00h UTC (em vez de 00h BRT), este mesmo instante já
    # cairia na semana seguinte -- é exatamente essa diferença que a
    # decisão de usar BRT resolve.
    almost_midnight_utc = datetime(2026, 8, 9, 23, 30, tzinfo=timezone.utc)
    start, end = _week_window(almost_midnight_utc)
    assert start == datetime(2026, 8, 3, 3, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 10, 3, 0, tzinfo=timezone.utc)


def test_week_window_is_exactly_seven_days():
    start, end = _week_window(datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc))
    assert end - start == timedelta(days=7)


# --- weekly_collections_count / progress ------------------------------


def test_weekly_progress_counts_only_reward_entries_inside_the_window():
    user_id = _create_user("uid-progress-1", "progress-1@example.com")
    week_start = datetime(2026, 8, 3, 3, 0, tzinfo=timezone.utc)
    inside = week_start + timedelta(days=2)
    before_window = week_start - timedelta(seconds=1)
    after_window = week_start + timedelta(days=7)

    for i in range(3):
        _credit_reward(user_id, Decimal("0.30"), f"session-{i}", created_at=inside)
    _credit_reward(user_id, Decimal("0.30"), "session-before", created_at=before_window)
    _credit_reward(user_id, Decimal("0.30"), "session-after", created_at=after_window)

    db = SessionLocal()
    try:
        count = weekly_collections_count(db, user_id, week_start, week_start + timedelta(days=7))
    finally:
        db.close()
    assert count == 3


def test_get_weekly_mission_status_reports_progress_capped_at_target():
    user_id = _create_user("uid-progress-2", "progress-2@example.com")
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    week_start, _ = _week_window(now)
    for i in range(WEEKLY_MISSION_TARGET + 2):
        _credit_reward(user_id, Decimal("0.30"), f"session-{i}", created_at=week_start + timedelta(hours=i))

    db = SessionLocal()
    try:
        status = get_weekly_mission_status(db, _get_user(user_id), now)
    finally:
        db.close()
    assert status.target == WEEKLY_MISSION_TARGET
    assert status.progress == WEEKLY_MISSION_TARGET
    assert status.completed is True


def test_get_weekly_mission_status_not_completed_below_target():
    user_id = _create_user("uid-progress-3", "progress-3@example.com")
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    week_start, _ = _week_window(now)
    for i in range(WEEKLY_MISSION_TARGET - 1):
        _credit_reward(user_id, Decimal("0.30"), f"session-{i}", created_at=week_start + timedelta(hours=i))

    db = SessionLocal()
    try:
        status = get_weekly_mission_status(db, _get_user(user_id), now)
    finally:
        db.close()
    assert status.progress == WEEKLY_MISSION_TARGET - 1
    assert status.completed is False


# --- multiplicador: ativação, expiração --------------------------------


def test_maybe_activate_fires_exactly_on_the_target_collection():
    user_id = _create_user("uid-activate-1", "activate-1@example.com")
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    week_start, _ = _week_window(now)
    for i in range(WEEKLY_MISSION_TARGET - 1):
        _credit_reward(user_id, Decimal("0.30"), f"session-{i}", created_at=week_start + timedelta(hours=i))

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        activated_early = maybe_activate_weekly_mission(db, user, now)
        db.commit()
    finally:
        db.close()
    assert activated_early is False
    assert _get_user(user_id).weekly_mission_multiplier_until is None

    # A décima entra agora -- essa SIM cruza o alvo.
    _credit_reward(user_id, Decimal("0.30"), "session-target", created_at=now)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        activated_now = maybe_activate_weekly_mission(db, user, now)
        db.commit()
    finally:
        db.close()
    assert activated_now is True
    until = _get_user(user_id).weekly_mission_multiplier_until
    assert until == now + WEEKLY_MISSION_MULTIPLIER_DURATION


def test_maybe_activate_does_not_refire_past_the_target():
    """"== target", não ">=": depois que a semana já passou de 10 coletas,
    novas coletas não devem reagendar o multiplicador de novo."""
    user_id = _create_user("uid-activate-2", "activate-2@example.com")
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    week_start, _ = _week_window(now)
    for i in range(WEEKLY_MISSION_TARGET + 1):
        _credit_reward(user_id, Decimal("0.30"), f"session-{i}", created_at=week_start + timedelta(hours=i))

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        activated = maybe_activate_weekly_mission(db, user, now)
        db.commit()
    finally:
        db.close()
    assert activated is False


def test_is_multiplier_active_true_within_window_false_after_expiry():
    user_id = _create_user("uid-expiry-1", "expiry-1@example.com")
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)

    _set_multiplier_until(user_id, now + timedelta(hours=1))
    assert is_multiplier_active(_get_user(user_id), now) is True

    _set_multiplier_until(user_id, now - timedelta(seconds=1))
    assert is_multiplier_active(_get_user(user_id), now) is False

    _set_multiplier_until(user_id, None)
    assert is_multiplier_active(_get_user(user_id), now) is False


def test_weekly_mission_status_exposes_multiplier_state():
    user_id = _create_user("uid-status-multiplier", "status-multiplier@example.com")
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    expires_at = now + timedelta(hours=5)
    _set_multiplier_until(user_id, expires_at)

    db = SessionLocal()
    try:
        status = get_weekly_mission_status(db, _get_user(user_id), now)
    finally:
        db.close()
    assert status.multiplier_active is True
    assert status.multiplier == WEEKLY_MISSION_MULTIPLIER
    assert status.multiplier_expires_at == expires_at


# --- GET /missions/weekly ------------------------------------------------


def test_weekly_mission_endpoint_returns_zero_progress_for_new_user(client: TestClient, monkeypatch):
    _register_user(client, monkeypatch, "uid-endpoint-1", "endpoint-1@example.com")
    response = client.get("/missions/weekly", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["target"] == WEEKLY_MISSION_TARGET
    assert body["progress"] == 0
    assert body["completed"] is False
    assert body["multiplier_active"] is False
    assert body["multiplier_expires_at"] is None


def test_weekly_mission_endpoint_requires_auth(client: TestClient):
    response = client.get("/missions/weekly")
    assert response.status_code in (401, 403)
