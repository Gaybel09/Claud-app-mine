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

## Deploy (Render)

`render.yaml` na raiz define o Blueprint: serviço web (gunicorn + worker
uvicorn), Postgres e Redis (Key Value) gerenciados. `DATABASE_URL` e
`REDIS_URL` vêm prontos desses serviços via `fromDatabase`/`fromService` --
não são hardcoded. As migrations (`alembic upgrade head`) rodam no
`startCommand`, antes do servidor subir, a cada deploy.

O worker Celery (`app/workers/`) ainda não está no blueprint -- só a API +
banco + cache, conforme a Fase 1.

`FIREBASE_CREDENTIALS_JSON`/`FIREBASE_CREDENTIALS_FILE` e as variáveis
`EFI_*` (ver seção "Integração Pix (Efí)" abaixo) precisam ser configuradas
manualmente no dashboard da Render depois do primeiro deploy (não vão em
texto claro no blueprint).

## Integração Pix (Efí)

Saques (`POST /pix/withdraw`, seção 11) são enviados via Pix Out da Efí
(sejaefi.com.br), sandbox por padrão. Variáveis necessárias:

| Variável | Onde conseguir | Obrigatória? |
|---|---|---|
| `EFI_CLIENT_ID` | Painel Efí -> "Minhas Aplicações" -> aplicação com escopo `pix.send` | sim |
| `EFI_CLIENT_SECRET` | Mesmo lugar que `EFI_CLIENT_ID` | sim |
| `EFI_CERTIFICATE_PATH` | Painel Efí -> "Certificados" -> gerar/baixar o certificado da conta (.p12/.pem); caminho do arquivo no disco | uma das duas (`_PATH` ou `_BASE64`) |
| `EFI_CERTIFICATE_BASE64` | O mesmo arquivo de certificado, mas o conteúdo em base64 como texto (`base64 -w0 certificado.pem`) -- não precisa de arquivo montado, tem prioridade sobre `EFI_CERTIFICATE_PATH` | uma das duas |
| `EFI_SANDBOX` | `true` (sandbox/homologação) ou `false` (produção) -- você mesmo escolhe, não vem da Efí | sim (default `true`) |
| `EFI_PAYER_PIX_KEY` | Uma chave Pix que você mesmo cadastra na sua conta Efí, usada como "pagador" no envio -- não é fornecida pela Efí, é configuração da sua conta | sim |

Toda chamada à API da Efí (inclusive a autenticação OAuth2) exige mTLS com
esse certificado -- é por isso que ele é obrigatório e não só client_id/
secret.

Configure também o webhook de envio de Pix no painel da Efí apontando para
`https://SEU_HOST/pix/webhook`.

O saldo só é debitado quando `POST /pix/webhook` confirma `status:
REALIZADO` -- nunca no momento de `POST /pix/withdraw`. Um worker Celery
periódico (`pix.reconcile_pending_withdrawals`, agendado a cada 5min via
Celery Beat em `app/workers/celery_app.py`) consulta a Efí diretamente para
todo saque parado em `processing` há mais de 10 minutos, para não depender
só do webhook. Esse worker/beat ainda não está no `render.yaml` -- precisa
de um serviço `celery -A app.workers.celery_app worker` e outro `celery -A
app.workers.celery_app beat` rodando além da API.
