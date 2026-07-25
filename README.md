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

A Efí exige que `idEnvio` (o identificador do envio, na URL de `PUT
/v3/gn/pix/:idEnvio`) case com `^[a-zA-Z0-9]{1,35}$` -- só alfanumérico, sem
hífen. Como `Idempotency-Key` é escolhida por quem chama `POST
/pix/withdraw` (normalmente um UUID, com hífens), o backend nunca manda essa
chave direto: `withdrawals.efi_id_envio` é derivado dela de forma
determinística (`app.core.efi.derive_id_envio`, um hash truncado) e é esse
valor que vai pra Efí e volta no webhook (`gnExtras.idEnvio`) -- a mesma
`Idempotency-Key` sempre gera o mesmo `efi_id_envio`, preservando a garantia
de idempotência real da Efí.

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

### Diagnóstico: `GET /admin/smoke-test/pix`

Roda, dentro do próprio processo do backend (sem nenhuma chamada HTTP
externa a si mesmo), os mesmos 7 passos do fluxo completo: cadastro → cubo
inicial → anúncio confirmado → mineração (com o relógio adiantado
diretamente via banco, sem esperar o ciclo real) → saldo → saque Pix → status
final do saque. Útil para validar de ponta a ponta que a integração Pix
sandbox da Efí está funcionando em produção, sem depender de acesso externo
ao banco nem de esperar o ciclo de mineração de verdade.

**Só fica acessível se `ADMIN_SMOKE_TEST_TOKEN` estiver configurada** -- sem
essa variável, o endpoint responde `404` como se não existisse. Gere um
valor forte com:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

e chame passando o mesmo valor no header `X-Admin-Token`:

```bash
curl -H "X-Admin-Token: SEU_TOKEN" https://SEU_HOST/admin/smoke-test/pix
```

Se estiver testando pelo navegador (ex: celular, sem acesso a curl/
terminal para setar headers), o mesmo token também pode ir na query
string, em vez do header:

```
https://SEU_HOST/admin/smoke-test/pix?token=SEU_TOKEN
```

Os dois métodos usam a mesma comparação seletiva por tempo constante
(`secrets.compare_digest`) e o mesmo comportamento fail-closed: se nenhum
dos dois bater (ou nenhum for enviado), a resposta é `403`; sem
`ADMIN_SMOKE_TEST_TOKEN` configurada, é sempre `404`.

A resposta traz `overall` (`"ok"`, `"failed"` ou `"not_configured"` se
`EFI_PAYER_PIX_KEY` não estiver setada) e um `steps` com o resultado de cada
uma das 7 etapas. Os dados criados (usuário, cubo, sessão de mineração,
ledger entries, withdrawal) são sempre apagados ao final, sucesso ou falha,
e o saldo do `reward_fund` é restaurado ao valor exato de antes -- mas o
envio de Pix disparado é real (para `EFI_PAYER_PIX_KEY`, contra o ambiente
sandbox da Efí).

Se o saque (etapa `pix_withdraw`) terminar com `status: "failed"`, o campo
`failure_reason` (nas etapas `pix_withdraw` e `pix_withdrawals_list`) traz o
motivo reportado pela Efí -- ex: `"HTTP 422: chave Pix do favorecido nao
encontrada"` (rejeição imediata no envio) ou `"PIX_KEY_INVALID: chave Pix
inexistente"` (`gnExtras.error` de um webhook `NAO_REALIZADO`). Esse motivo
fica salvo em `withdrawals.failure_reason` para qualquer saque, mas só é
exposto aqui, no diagnóstico -- nunca em `POST /pix/withdraw` ou `GET
/pix/withdrawals` (a API que o app usa).

**ATENÇÃO**: isto é só para diagnóstico manual em sandbox. Remova a rota
(ou pare de configurar `ADMIN_SMOKE_TEST_TOKEN`) antes de operar fora de
sandbox, em produção de verdade.

### Diagnóstico: `GET /admin/register-efi-webhook`

Registra na Efí (`PUT /v2/webhook/:chave`) a URL de webhook de envio de Pix
para `EFI_PAYER_PIX_KEY`, apontando para `PUBLIC_BASE_URL` + `/pix/webhook`
(`PUBLIC_BASE_URL` já vem configurada com o host atual no Render -- ver
`.env.example`/`render.yaml`). Alternativa a configurar isso manualmente no
painel da Efí (Webhooks). Usa as mesmas credenciais já configuradas
(`EFI_CLIENT_ID`/`EFI_CLIENT_SECRET`/certificado mTLS).

Mesma proteção que `/admin/smoke-test/pix`: exige `ADMIN_SMOKE_TEST_TOKEN`
via header `X-Admin-Token` ou query string `?token=`, mesmo comportamento
fail-closed (`404` sem a variável configurada, `403` se o token não bater).

```bash
curl -H "X-Admin-Token: SEU_TOKEN" https://SEU_HOST/admin/register-efi-webhook
```

A resposta traz `ok` (`true`/`false`), `pix_key`, `webhook_url` e, em caso de
sucesso, `efi_response` (o corpo devolvido pela Efí); em caso de falha,
`error` com o motivo (ex: `"HTTP 400: ..."` se a Efí rejeitar a URL, ou
`"EFI_PAYER_PIX_KEY is not configured"` se a chave não estiver setada).

**ATENÇÃO**: isto é só para diagnóstico manual em sandbox -- faz uma
chamada real de escrita na conta Efí (registra/sobrescreve a URL de webhook
associada à chave). Remova a rota (ou pare de configurar
`ADMIN_SMOKE_TEST_TOKEN`) antes de operar fora de sandbox, em produção de
verdade.
