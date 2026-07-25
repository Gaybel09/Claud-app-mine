from fastapi.testclient import TestClient

from app.core import firebase


def _fake_verify(uid: str, email: str):
    def _verify(id_token: str) -> dict:
        if id_token != "valid-token":
            raise firebase.InvalidFirebaseTokenError("bad token")
        return {"uid": uid, "email": email}

    return _verify


def _auth_header(token: str = "valid-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_blocked_by_per_token_limit_after_five_attempts(client: TestClient, monkeypatch):
    """REGISTER_LIMIT_PER_TOKEN == "5/hour" -- a mesma credencial repetindo
    a chamada (mesmo depois de já registrada, tomando 409) ainda conta pro
    limite, porque o check roda antes da lógica de duplicidade."""
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-rl-token", "rl-token@example.com"))

    statuses = [client.post("/auth/register", json={}, headers=_auth_header()).status_code for _ in range(6)]

    assert statuses[0] == 201
    assert statuses[1:5] == [409, 409, 409, 409]
    assert statuses[5] == 429


def test_register_blocked_by_per_ip_limit_even_across_different_tokens(client: TestClient, monkeypatch):
    """REGISTER_LIMIT_PER_IP == "5/hour" -- protege mesmo quando cada
    tentativa usa uma credencial (uid) diferente, então o limite por
    credencial sozinho nunca dispararia; o TestClient sempre simula o
    mesmo IP, então esse é o cenário "várias contas, um IP só"."""
    statuses = []
    for i in range(6):
        uid = f"uid-rl-ip-{i}"
        monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify(uid, f"{uid}@example.com"))
        statuses.append(client.post("/auth/register", json={}, headers=_auth_header()).status_code)

    assert statuses[:5] == [201, 201, 201, 201, 201]
    assert statuses[5] == 429


def test_rate_limit_response_body(client: TestClient, monkeypatch):
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-rl-body", "rl-body@example.com"))

    for _ in range(5):
        client.post("/auth/register", json={}, headers=_auth_header())
    response = client.post("/auth/register", json={}, headers=_auth_header())

    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["error"]


def test_login_not_rate_limited_before_reaching_the_limit(client: TestClient, monkeypatch):
    """Confirma que o limite generoso do login (30/min por IP, 20/min por
    token) não atrapalha uso normal -- só entra em cena bem acima disso."""
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-rl-login", "rl-login@example.com"))
    client.post("/auth/register", json={}, headers=_auth_header())

    statuses = [client.post("/auth/login", headers=_auth_header()).status_code for _ in range(10)]
    assert all(status == 200 for status in statuses)


def test_ads_watch_blocked_by_per_token_limit(client: TestClient, monkeypatch):
    """ADS_WATCH_LIMIT_PER_TOKEN == "20/minute" -- prova que o rate limit
    também está ligado numa rota fora de /auth, não só ali."""
    monkeypatch.setattr(firebase, "verify_firebase_token", _fake_verify("uid-rl-ads", "rl-ads@example.com"))
    register_response = client.post("/auth/register", json={}, headers=_auth_header())
    assert register_response.status_code == 201

    statuses = [
        client.post("/ads/watch", json={"ad_network": "test-network"}, headers=_auth_header()).status_code
        for _ in range(21)
    ]

    assert statuses[:20] == [201] * 20
    assert statuses[20] == 429


def test_failed_auth_does_not_count_against_the_rate_limit(client: TestClient):
    """Uma requisição rejeitada por token ausente/inválido (401) nunca
    chega a rodar o corpo da rota decorada -- então não incrementa nenhum
    contador. Confirma isso rodando bem mais vezes que o limite (5/hora)
    sem nunca virar 429."""
    statuses = [client.post("/auth/register", json={}).status_code for _ in range(8)]
    assert all(status == 401 for status in statuses)
