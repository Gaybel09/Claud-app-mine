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
| `EFI_CERTIFICATE_PEM` | Painel Efí -> "Meus certificados" -> gera um `.p12`. Converta pra PEM combinado (`openssl pkcs12 -in cert.p12 -out cert.pem -nodes -legacy`) e cole o conteúdo do `.pem` aqui como texto | uma das três (`_PEM`, `_BASE64` ou `_PATH`) |
| `EFI_CERTIFICATE_BASE64` | O mesmo `cert.pem` acima, mas em base64 (`base64 -w0 cert.pem`) | uma das três |
| `EFI_CERTIFICATE_PATH` | O mesmo `cert.pem`, mas como caminho de arquivo no disco (ex: um Secret File já montado) | uma das três |
| `EFI_SANDBOX` | `true` (sandbox/homologação) ou `false` (produção) -- você mesmo escolhe, não vem da Efí | sim (default `true`) |
| `EFI_PAYER_PIX_KEY` | Uma chave Pix que você mesmo cadastra na sua conta Efí, usada como "pagador" no envio -- não é fornecida pela Efí, é configuração da sua conta | sim |

Toda chamada à API da Efí (inclusive a autenticação OAuth2) exige mTLS com
esse certificado -- é por isso que ele é obrigatório e não só client_id/
secret. A Efí só entrega o certificado em `.p12` (PKCS#12); o Python não lê
esse formato direto, por isso a conversão pra PEM combinado é sempre
necessária antes de usar qualquer uma das três variáveis acima. Quando mais
de uma estiver setada, a prioridade é `EFI_CERTIFICATE_PEM` >
`EFI_CERTIFICATE_BASE64` > `EFI_CERTIFICATE_PATH`.

Configure também o webhook de envio de Pix no painel da Efí apontando para
`https://SEU_HOST/pix/webhook`.

Depois de configurar tudo, confirme que a autenticação OAuth2 com a Efí está
funcionando de verdade, sem precisar fazer um saque real:

```bash
curl https://SEU_HOST/pix/health
```

`200 {"status": "ok"}` = autenticou; `503` = falha (credenciais ausentes,
client_id/secret errado, ou certificado inválido) -- o detalhe do erro nunca
inclui o corpo cru da resposta da Efí, só o status HTTP. Não exige login;
cada chamada faz uma autenticação real (não reaproveita token cacheado), só
para diagnóstico.

O saldo só é debitado quando `POST /pix/webhook` confirma `status:
REALIZADO` -- nunca no momento de `POST /pix/withdraw`. Um worker Celery
periódico (`pix.reconcile_pending_withdrawals`, agendado a cada 5min via
Celery Beat em `app/workers/celery_app.py`) consulta a Efí diretamente para
todo saque parado em `processing` há mais de 10 minutos, para não depender
só do webhook. Esse worker/beat ainda não está no `render.yaml` -- precisa
de um serviço `celery -A app.workers.celery_app worker` e outro `celery -A
app.workers.celery_app beat` rodando além da API.
