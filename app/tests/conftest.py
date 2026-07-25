import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.rate_limit import limiter
from app.db.session import engine
from app.main import app


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
        # reward_fund/reward_config have no FK to users, so the cascade
        # above doesn't touch them -- reset both singleton rows back to
        # their seeded state.
        connection.execute(
            text("UPDATE reward_fund SET balance = 0, total_in = 0, total_out = 0, updated_at = now() WHERE id = 1")
        )
        connection.execute(
            text(
                "UPDATE reward_config SET value_per_session = 0.30, avg_ecpm = NULL, updated_at = now() "
                "WHERE id = 1"
            )
        )


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """O rate limiter (app/core/rate_limit.py) guarda contadores no Redis,
    fora do banco -- sem isso, testes de rotas diferentes que chamam a
    mesma rota (ex: /auth/register) acabariam compartilhando o mesmo
    contador ao longo da suíte inteira (TestClient usa sempre o mesmo IP
    simulado) e começariam a tomar 429 por causa de OUTROS testes, não do
    próprio. reset() só limpa as chaves com o prefixo do limiter (ver
    key_prefix em rate_limit.py), nunca o Redis inteiro."""
    yield
    limiter.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
