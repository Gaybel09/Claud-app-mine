import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import firebase
from app.db.session import SessionLocal
from app.models.ledger_entry import LedgerEntry, LedgerEntryType
from app.modules.wallet.service import compute_balance, create_ledger_entry, get_cached_balance


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


def test_balance_sums_multiple_entry_types(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-balance", "balance@example.com")

    db = SessionLocal()
    try:
        create_ledger_entry(db, user_id, LedgerEntryType.REWARD, Decimal("50.00"), "session-1")
        create_ledger_entry(db, user_id, LedgerEntryType.BONUS, Decimal("10.00"), "bonus-1")
        create_ledger_entry(db, user_id, LedgerEntryType.FEE, Decimal("-2.50"), "fee-1")
        create_ledger_entry(db, user_id, LedgerEntryType.WITHDRAWAL, Decimal("-20.00"), "withdrawal-1")
        db.commit()
    finally:
        db.close()

    response = client.get("/wallet/balance", headers=_auth_header())
    assert response.status_code == 200
    assert Decimal(str(response.json()["balance"])) == Decimal("37.50")


def test_balance_cache_matches_real_ledger_sum(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-cache", "cache@example.com")

    db = SessionLocal()
    try:
        create_ledger_entry(db, user_id, LedgerEntryType.REWARD, Decimal("15.00"), "session-1")
        db.commit()
        real_balance = compute_balance(db, user_id)
    finally:
        db.close()

    response = client.get("/wallet/balance", headers=_auth_header())
    assert response.status_code == 200

    cached = get_cached_balance(user_id)
    assert cached is not None
    assert cached == real_balance


def test_create_ledger_entry_rejects_wrong_sign_for_type(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-sign", "sign@example.com")

    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            create_ledger_entry(db, user_id, LedgerEntryType.REWARD, Decimal("-5.00"), None)
        with pytest.raises(ValueError):
            create_ledger_entry(db, user_id, LedgerEntryType.FEE, Decimal("5.00"), None)
    finally:
        db.rollback()
        db.close()


def test_create_ledger_entry_concurrent_writes_keep_balance_consistent(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-concurrent", "concurrent@example.com")

    workers = 10
    amount = Decimal("1.00")
    errors: list[Exception] = []

    def _worker():
        session = SessionLocal()
        try:
            create_ledger_entry(session, user_id, LedgerEntryType.REWARD, amount, None)
            session.commit()
        except Exception as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=_worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors

    db = SessionLocal()
    try:
        final_balance = compute_balance(db, user_id)
        balances_after = [
            row[0]
            for row in db.query(LedgerEntry.balance_after)
            .filter(LedgerEntry.user_id == user_id)
            .order_by(LedgerEntry.balance_after)
            .all()
        ]
    finally:
        db.close()

    assert final_balance == amount * workers
    # No two concurrent writers should have computed the same running total --
    # that would mean one write clobbered the other's view of the balance.
    assert len(balances_after) == len(set(balances_after)) == workers
    assert balances_after == [amount * i for i in range(1, workers + 1)]


def test_statement_returns_entries_in_descending_order_paginated(client: TestClient, monkeypatch):
    user_id = _register_user(client, monkeypatch, "uid-statement", "statement@example.com")

    db = SessionLocal()
    try:
        for i in range(5):
            create_ledger_entry(db, user_id, LedgerEntryType.REWARD, Decimal("1.00"), f"session-{i}")
            db.commit()
    finally:
        db.close()

    page1 = client.get("/wallet/statement", params={"page": 1, "page_size": 2}, headers=_auth_header())
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 5
    assert [item["reference_id"] for item in body1["items"]] == ["session-4", "session-3"]

    page2 = client.get("/wallet/statement", params={"page": 2, "page_size": 2}, headers=_auth_header())
    body2 = page2.json()
    assert [item["reference_id"] for item in body2["items"]] == ["session-2", "session-1"]

    page3 = client.get("/wallet/statement", params={"page": 3, "page_size": 2}, headers=_auth_header())
    body3 = page3.json()
    assert [item["reference_id"] for item in body3["items"]] == ["session-0"]
