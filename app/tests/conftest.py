import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import engine
from app.main import app


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        # reward_fund has no FK to users, so the cascade above doesn't touch
        # it -- reset the singleton row back to its seeded state.
        connection.execute(
            text("UPDATE reward_fund SET balance = 0, total_in = 0, total_out = 0, updated_at = now() WHERE id = 1")
        )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
