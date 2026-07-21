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


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
