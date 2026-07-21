# CubeMine Pix — Backend

Fundação do backend do CubeMine Pix (Fase 1 — setup do projeto). Nenhum
módulo de negócio está implementado ainda; esta é só a base sobre a qual os
próximos módulos (auth, wallet, ads, mining) serão construídos.

> O documento `cubemine-pix-plano-tecnico-corrigido.md` referenciado pelos
> prompts da Fase 1 ainda não está neste repositório. Adicione-o na raiz do
> projeto antes de seguir para os próximos prompts (2-8), que dependem dele.

## Stack

- FastAPI + SQLAlchemy 2.0 + Alembic
- PostgreSQL + Redis via docker-compose
- Celery (worker, configurado mas sem tasks de negócio ainda)
- pytest

## Estrutura

```
app/
  core/      # configuração (Settings via pydantic-settings)
  db/        # engine, sessão, Base declarativa
  models/    # models SQLAlchemy (vazio por enquanto)
  schemas/   # schemas Pydantic (vazio por enquanto)
  modules/   # módulos de domínio (só health/ por enquanto)
  workers/   # app Celery
  tests/     # testes pytest
alembic/     # migrations
```

## Rodando localmente

```bash
cp .env.example .env
docker compose up --build
```

A API sobe em `http://localhost:8000`. Verifique a saúde da API e a conexão
com o banco:

```bash
curl http://localhost:8000/health
```

## Migrations

```bash
docker compose exec api alembic revision --autogenerate -m "mensagem"
docker compose exec api alembic upgrade head
```

## Testes

```bash
pip install -r requirements.txt
POSTGRES_HOST=localhost REDIS_HOST=localhost pytest
```
