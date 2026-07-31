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

**Atenção**: a Efí acrescenta automaticamente o sufixo `/pix` a QUALQUER URL
registrada em `PUT /v2/webhook/:chave` (não é opcional -- ver
[dev.efipay.com.br/en/docs/api-pix/gestao-de-pix/](https://dev.efipay.com.br/en/docs/api-pix/gestao-de-pix/)).
Ou seja, a notificação de verdade chega em `/pix/webhook/pix`, não em
`/pix/webhook` -- por isso `POST /pix/webhook/pix` existe como alias da
mesma rota (`app/modules/pix/router.py`). Não registre a URL já com esse
sufixo (`.../pix/webhook/pix`): a Efí acrescentaria outro `/pix` por cima.

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

O saldo só é debitado quando `POST /pix/webhook` (ou `/pix/webhook/pix` --
ver nota sobre o sufixo automático da Efí logo abaixo) confirma `status:
REALIZADO` -- nunca no momento de `POST /pix/withdraw`. A confiabilidade do
webhook sozinho nunca foi comprovada (ver `POST /admin/withdrawals/{id}/
reconcile`, a via manual usada pra investigar isso -- saque #10 ficou
34+min preso em `processing` mesmo com o webhook já corrigido), então
existem DUAS redes de segurança independentes dele, cobrindo todo saque
parado em `processing` há mais de `RECONCILE_AFTER_MINUTES` (3min,
`app/modules/pix/service.py`):

1. **`POST /admin/withdrawals/reconcile-all`** (`app/modules/admin/router.py`,
   protegido por `ADMIN_SMOKE_TEST_TOKEN`, mesmo padrão de
   `/admin/update-reward-config` -- funciona mesmo com
   `ENABLE_DIAGNOSTIC_ENDPOINTS` desligada, porque precisa continuar
   acessível em produção real). Reconcilia TODOS os saques presos de uma
   vez, chamável por HTTP sem esperar nada -- pensado pra ser acionado por
   um agendador externo gratuito. Ver `.github/workflows/
   reconcile-withdrawals.yml`: um workflow do GitHub Actions que chama esse
   endpoint a cada 5min via `cron`, sem custar nada (cota gratuita do
   Actions), enquanto o Background Worker de verdade (item 2) não está
   aprovado/implantado. Requer o secret `ADMIN_SMOKE_TEST_TOKEN` configurado
   no repositório (Settings -> Secrets and variables -> Actions), com o
   MESMO valor já configurado no dashboard do Render.
2. **Worker Celery periódico** (`pix.reconcile_pending_withdrawals`,
   `app/workers/celery_app.py`) -- roda como processo dedicado 24/7
   (serviço `cubemine-pix-reconcile-worker` no `render.yaml`, `celery -A
   app.workers.celery_app worker --beat`, beat embutido, checando a cada
   60s). Mais caro (Background Worker é cobrado pelo mês inteiro, ao
   contrário do Cron Job/GitHub Actions do item 1) mas não depende de um
   serviço externo (GitHub Actions) nem de um cron de 5min em vez de 60s.
   **Assim que este worker estiver aprovado e implantado, desative o
   workflow do GitHub Actions do item 1** (Settings -> Actions -> disable
   workflow, ou apague o arquivo) -- deixar os dois rodando ao mesmo tempo
   não quebra nada (reconciliar um saque já resolvido é um no-op), só
   desperdiça chamadas. Nunca escale esse serviço para mais de 1 instância
   (o beat embutido duplicaria as tarefas agendadas).

### Migração de homologação para produção

Passo a passo pra virar a chave de sandbox pra produção de verdade
(dinheiro real):

1. **Gere o certificado de produção** no painel Efí -> "Meus certificados"
   (aplicação de produção, não a de homologação) -- baixa um `.p12`.
2. **Converta pra PEM combinado**:
   ```bash
   openssl pkcs12 -in producao.p12 -out producao.pem -nodes -legacy -passin pass:
   ```
   (`-passin pass:` funciona se a Efí exportou com senha vazia -- comum;
   se pedir senha, tire o `-passin pass:` e digite quando solicitado). O
   `-legacy` é necessário no OpenSSL 3.x porque o `.p12` da Efí usa
   3DES/SHA1 (algoritmo antigo). Confirme que o resultado tem exatamente
   um bloco `BEGIN CERTIFICATE` e um `BEGIN PRIVATE KEY`.
3. **No dashboard do Render**, atualize (não precisa mexer no
   `render.yaml` -- essas 3 variáveis já são `sync: false`, geridas só
   pelo dashboard):
   - `EFI_CLIENT_ID` -> o Client ID da aplicação de **produção**
   - `EFI_CLIENT_SECRET` -> o Client Secret da aplicação de **produção**
   - `EFI_CERTIFICATE_PEM` -> conteúdo do `producao.pem` (o texto inteiro,
     dos dois `-----BEGIN...-----END-----`)
   - `EFI_PAYER_PIX_KEY` -> a chave Pix real da conta Efí de produção que
     paga os saques (**não** é a mesma de homologação -- confira antes)
4. **Mude `EFI_SANDBOX` para `false`** -- essa é a única variável que
   *não* é `sync: false`, então precisa de uma mudança no `render.yaml`
   (commitada e com push) para valer.
5. **Re-registre o webhook** contra o ambiente de produção:
   `GET /admin/register-efi-webhook` (com `ENABLE_DIAGNOSTIC_ENDPOINTS`
   ligada temporariamente) -- o webhook registrado para homologação NÃO
   vale pra produção, são hosts Efí diferentes.
6. **Valide sem mover dinheiro**: `GET /pix/health` autentica de verdade
   contra a Efí de produção sem fazer nenhum saque -- rode isso antes de
   qualquer saque real. **Não rode `GET /admin/smoke-test/pix` em
   produção** -- ele sempre manda o saque de teste para
   `efipay@sejaefi.com.br`, a chave de homologação, que não existe/não é
   confirmada no ambiente de produção (só serve pra sandbox).

Depois do passo 4, qualquer saque real (`POST /pix/withdraw`) passa a
mover dinheiro de verdade -- confirme os passos 1-3 e 5-6 antes.

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
envio de Pix disparado é real, contra o ambiente sandbox da Efí.

O saque de teste sempre vai para `efipay@sejaefi.com.br` (chave `favorecido`,
constante `EFI_SANDBOX_HOMOLOGATION_PIX_KEY` em `smoke_test.py`) -- nunca
para `EFI_PAYER_PIX_KEY` nem qualquer outra configuração. É a chave oficial
de homologação da Efí ([dev.efipay.com.br/docs/api-pix/envio-pagamento-pix](https://dev.efipay.com.br/docs/api-pix/envio-pagamento-pix),
seção "Instruções para testes em Homologação"): em sandbox, só saques para
EXATAMENTE essa chave são confirmados/rejeitados de verdade (valores entre
R$0,01 e R$10,00, faixa em que `reward.MIN_REWARD`/`MAX_REWARD` sempre
caem); qualquer outra chave -- mesmo uma chave real válida -- dá
`chave_favorecido_nao_encontrada`. É específica do sandbox de homologação:
`POST /pix/withdraw` (a API que o app usa) nunca usa essa constante, só o
`pix_key` do usuário de verdade.

Se o saque (etapa `pix_withdraw`) terminar com `status: "failed"`, o campo
`failure_reason` (nas etapas `pix_withdraw` e `pix_withdrawals_list`) traz o
motivo reportado pela Efí -- ex: `"HTTP 422: chave Pix do favorecido nao
encontrada"` (rejeição imediata no envio) ou `"PIX_KEY_INVALID: chave Pix
inexistente"` (`gnExtras.error` de um webhook `NAO_REALIZADO`). Esse motivo
fica salvo em `withdrawals.failure_reason` para qualquer saque, mas só é
exposto aqui, no diagnóstico -- nunca em `POST /pix/withdraw` ou `GET
/pix/withdrawals` (a API que o app usa).

Passe `?force_reconcile=true` para rodar, logo depois do saque, a mesma
lógica do worker periódico (`pix.reconcile_pending_withdrawals`) na hora --
sem esperar o agendamento do Celery Beat (60s) nem o corte de
`RECONCILE_AFTER_MINUTES` (3min). Útil pra confirmar que o fluxo funciona
só com a reconciliação, sem depender do webhook receber corretamente (ex:
mTLS de recebimento não é viável no plano gratuito do Render). Adiciona uma
etapa `pix_reconcile` com `status_before`/`status_after`/`failure_reason`,
mostrando a transição de status do saque causada pela consulta real à Efí
(`GET /v2/gn/pix/enviados/id-envio/:idEnvio`).

**ATENÇÃO**: isto é só para diagnóstico manual, com uma segunda camada de
proteção além do token -- ver `ENABLE_DIAGNOSTIC_ENDPOINTS` mais abaixo.

### Diagnóstico: `GET /admin/register-efi-webhook`

Registra na Efí (`PUT /v2/webhook/:chave`) a URL de webhook de envio de Pix
para `EFI_PAYER_PIX_KEY`, apontando para `PUBLIC_BASE_URL` + `/pix/webhook`
(`PUBLIC_BASE_URL` já vem configurada com o host atual no Render -- ver
`.env.example`/`render.yaml`). Alternativa a configurar isso manualmente no
painel da Efí (Webhooks). Usa as mesmas credenciais já configuradas
(`EFI_CLIENT_ID`/`EFI_CLIENT_SECRET`/certificado mTLS).

A chamada sempre inclui `x-skip-mtls-checking: true` -- por padrão, a Efí
exige que o próprio servidor de webhook valide o certificado mTLS dela nas
notificações recebidas ([dev.efipay.com.br/docs/api-pix/webhooks#entendendo-o-padrão-mtls](https://dev.efipay.com.br/docs/api-pix/webhooks#entendendo-o-padrão-mtls));
como não temos essa validação configurada (hospedado no Render, sem esse
setup), esse header avisa a Efí para não exigir mTLS de entrada -- sem ele,
o registro falha com `webhook_invalido` porque a checagem de
acessibilidade da URL feita pela Efí recebe uma resposta que ela não
consegue validar. É um valor fixo em `EfiPixClient.WEBHOOK_SKIP_MTLS_CHECKING`
(não depende de env var); se o servidor um dia passar a validar mTLS de
entrada de verdade, esse valor precisa virar `"false"`.

Mesma proteção que `/admin/smoke-test/pix`: exige `ADMIN_SMOKE_TEST_TOKEN`
via header `X-Admin-Token` ou query string `?token=`, mesmo comportamento
fail-closed (`404` sem a variável configurada, `403` se o token não bater)
-- e a mesma segunda camada, `ENABLE_DIAGNOSTIC_ENDPOINTS` (ver abaixo).

```bash
curl -H "X-Admin-Token: SEU_TOKEN" https://SEU_HOST/admin/register-efi-webhook
```

A resposta traz `ok` (`true`/`false`), `pix_key`, `webhook_url` e, em caso de
sucesso, `efi_response` (o corpo devolvido pela Efí); em caso de falha,
`error` com o motivo (ex: `"HTTP 400: ..."` se a Efí rejeitar a URL, ou
`"EFI_PAYER_PIX_KEY is not configured"` se a chave não estiver setada).

**ATENÇÃO**: isto é só para diagnóstico manual -- faz uma chamada real de
escrita na conta Efí (registra/sobrescreve a URL de webhook associada à
chave). Segunda camada de proteção além do token -- ver
`ENABLE_DIAGNOSTIC_ENDPOINTS` abaixo.

### `ENABLE_DIAGNOSTIC_ENDPOINTS`: segunda camada de proteção

`GET /admin/smoke-test/pix` e `GET /admin/register-efi-webhook` cumpriram
a função de setup inicial (validar a integração Pix/Efí) e não devem ficar
acessíveis em produção de verdade só por trás de `ADMIN_SMOKE_TEST_TOKEN`
-- se esse token vazar ou for adivinhado, ele sozinho também dá acesso ao
painel admin de verdade (`promote-user`, `users`, `withdrawals`, `fund`),
então uma segunda camada independente, específica pra essas duas rotas de
diagnóstico, vale a pena.

`ENABLE_DIAGNOSTIC_ENDPOINTS` (`app/core/config.py`, default `false`,
fail-safe): sem essa variável ligada, as duas rotas respondem `404` mesmo
com o token certo. **Não afeta** `GET /admin/update-reward-config` (chamado
de verdade em produção, 1x/dia, pelo Cron Job -- ver seção de recompensa
variável) nem `promote-user`/`demote-user` (necessários mesmo em produção,
ver docstring de `promote_user` em `app/modules/admin/router.py`). Ligue
só temporariamente pelo dashboard do Render se precisar rodar o smoke test
ou reconfigurar o webhook da Efí (ex: a URL mudou), e desligue assim que
terminar.

## Painel admin (seção 10)

Visão básica de usuários, saques e fundo de recompensas, para operação
manual. Ao contrário dos diagnósticos de sandbox acima, exige login Firebase
normal de um usuário com `is_admin=true` -- não usa `ADMIN_SMOKE_TEST_TOKEN`.

**Promovendo o primeiro admin**: não existe (ainda) um jeito de um admin
promover outro pelo próprio painel, então a promoção é manual, via
`POST /admin/promote-user/{user_id}` -- protegida pelo mesmo
`ADMIN_SMOKE_TEST_TOKEN` das rotas de diagnóstico, por conveniência (reaproveita
a mesma infra de proteção já existente). Ao contrário delas, esta rota **não**
é "só sandbox": continua sendo a única forma de bootstrapar o primeiro admin
até existir um fluxo de convite de verdade.

```bash
curl -X POST -H "X-Admin-Token: SEU_TOKEN" https://SEU_HOST/admin/promote-user/42
```

`POST /admin/demote-user/{user_id}` reverte, com a mesma proteção.

### Rotas do painel (exigem `Authorization: Bearer <token Firebase>` de um admin)

| Rota | O que faz |
|---|---|
| `GET /admin/users?page=&page_size=` | Lista usuários com saldo atual, data de cadastro, `is_blocked`, `is_admin` -- paginado |
| `POST /admin/users/{id}/block` | Bloqueia um usuário (`is_blocked=true`) -- a partir daí, todo endpoint autenticado dele responde `403` |
| `POST /admin/users/{id}/unblock` | Desbloqueia |
| `GET /admin/withdrawals?status=&page=&page_size=` | Lista **todos** os saques do sistema (não só de um usuário), com `failure_reason` visível e filtro opcional por `status` (`pending`/`processing`/`paid`/`failed`) -- paginado |
| `POST /admin/withdrawals/{id}/approve` | Confirma manualmente que um saque foi pago -- ver aviso abaixo |
| `GET /admin/fund` | `balance`, `total_in`, `total_out` do `reward_fund`, e `low_balance_alert` (`true` se `balance < ADMIN_FUND_LOW_THRESHOLD`, configurável, default `50.00`) |
| `GET /admin/users/{id}/devices` | Antifraude básico (seção 11) -- quantos usuários distintos compartilham o mesmo `device_id` deste usuário. Ver seção abaixo |

**Sobre `POST /admin/withdrawals/{id}/approve`**: o fluxo normal de
confirmação é 100% automático -- via webhook (`POST /pix/webhook`/
`/pix/webhook/pix`) ou, se ele não chegar, via reconciliação periódica
(`pix.reconcile_pending_withdrawals`, a cada 60s, para saques parados em
`processing` há mais de `RECONCILE_AFTER_MINUTES`) rodando de verdade em
produção (serviço `cubemine-pix-reconcile-worker`, `render.yaml`). Há
também `POST /admin/withdrawals/{id}/reconcile` para reconciliar um saque
específico na hora, sem esperar o worker periódico. `POST
.../{id}/approve` abaixo é só a via de escape manual para
quando as duas falharem (ex: Efí fora do ar por um tempo prolongado) **e**
um admin já confirmou de forma independente, olhando o extrato/dashboard da
própria Efí, que a transferência realmente aconteceu -- ele debita o saldo
do usuário exatamente como uma confirmação real chegaria, então aprovar um
saque que na verdade falhou deixa o saldo incorreto. Idempotente (`200` sem
debitar de novo se já estiver `paid`); `400` se o saque já estiver `failed`
(estado terminal que não pode virar `paid`); `404` se o id não existir.

## Antifraude básico (seção 11)

Primeira camada de limitação de abuso -- visibilidade e limites básicos, não
um sistema de decisão de fraude completo (isso fica pra fases futuras).
**Não bloqueia nada automaticamente** além do rate limit em si.

### Rate limiting

`POST /auth/register`, `POST /auth/login`, `POST /ads/watch`,
`POST /mining/collect` e `POST /pix/withdraw` (as rotas mais expostas a
abuso automatizado) têm dois limites cada, via [slowapi](https://github.com/laurentS/slowapi)
com storage no Redis (`REDIS_URL`, compartilhado entre todas as instâncias
do serviço web -- ver `app/core/rate_limit.py`):

| Rota | Por IP | Por credencial (token) | Por quê |
|---|---|---|---|
| `POST /auth/register` | 5/hora | 5/hora | Cada cadastro gera um cubo inicial e passa a poder sacar do fundo -- o alvo é travar criação em massa de contas |
| `POST /auth/login` | 30/min | 20/min | Chamado a cada abertura do app/refresh de token -- limite generoso pra não atrapalhar uso normal, mas trava enumeração agressiva |
| `POST /ads/watch` | 60/min | 20/min | Assistir um anúncio de verdade leva tempo; 20/min já é folgado pra humano, trava scripts gerando `ad_view`s em volume |
| `POST /mining/collect` | 30/min | 10/min | Coleta deveria acontecer ~1x por ciclo (MINING_SESSION_DURATION_SECONDS, 30min por padrão); limita spam de polling/tentativas de abusar do lock de linha |
| `POST /pix/withdraw` | 10/hora | 5/hora | Operação financeira, a mais sensível -- um saque legítimo é esporádico, não repetido |

"Por IP" (`get_remote_address`) pega várias contas abusando a partir de um
único IP/rede; "por credencial" (hash do Bearer token cru, sem decodificar
de novo) pega uma única conta/token abusando a partir de IPs diferentes
(ex: troca de proxy). Nenhum dos dois sozinho cobre os dois cenários, por
isso as rotas aplicam os dois ao mesmo tempo. Uma requisição rejeitada por
autenticação (401) nunca chega a contar pro limite -- isso é intencional
(um 401 já é barato de rejeitar; o alvo é tráfego que passa da
autenticação). Excedeu o limite: `429` com
`{"error": "Rate limit exceeded: ..."}`.

### Device fingerprint básico

O app Flutter gera e persiste um identificador de device simples, mandado
no cadastro via header `X-Device-Id` -- opcional; sem ele, `device_id` fica
nulo. Só capturado no cadastro (`POST /auth/register`), nunca atualizado
depois.

`GET /admin/users/{id}/devices` (painel admin) mostra quantos usuários
distintos compartilham o mesmo `device_id` do usuário consultado --
`shared_user_count` inclui o próprio usuário, então `1` = não compartilhado,
`> 1` é o sinal de possível múltiplas contas no mesmo aparelho. Só
visibilidade pro admin decidir (ex: bloquear manualmente via
`POST /admin/users/{id}/block` depois de olhar o agrupamento) -- nada é
bloqueado automaticamente por compartilhar device_id.

## Integração de anúncios: Google Mobile Ads / RewardedAd (seção 7)

O app Flutter usa o SDK `google_mobile_ads` para o anúncio premiado
(RewardedAd) que libera o ciclo de mineração. Ao tocar em "ASSISTIR
ANÚNCIO" (`mobile/lib/controllers/mining_controller.dart`,
`RewardedAdService` em `mobile/lib/services/rewarded_ad_service.dart`), o
app carrega e exibe o anúncio; **só quando `onUserEarnedReward` dispara**
(anúncio assistido até o fim de verdade) é que o app chama
`POST /ads/watch` e `POST /ads/callback` para registrar e confirmar o
`ad_view`, liberando `POST /mining/start`. Se o anúncio falhar ao carregar
ou for fechado antes do fim, nada disso roda -- a mineração não é liberada.

**App ID** (`ca-app-pub-9407999187872272~5109632072`): configurado nos
manifests nativos (`android/app/src/main/AndroidManifest.xml`,
`ios/Runner/Info.plist`), sempre o real -- é seguro, porque é o Ad Unit ID,
não o App ID, que determina se o conteúdo servido é de teste ou de
verdade.

**Ad Unit ID** (`mobile/lib/core/ads_config.dart`): por padrão usa os IDs
de teste **oficiais do Google** (documentados em
[developers.google.com/admob/flutter/test-ads](https://developers.google.com/admob/flutter/test-ads),
sempre servem anúncio de teste, nunca geram risco pra conta AdMob real,
não importa a conta/dispositivo) -- para não arriscar a conta real
(`ca-app-pub-9407999187872272/9926844486`, bloco premiado do CubeMine
Pix) enquanto em desenvolvimento. Para usar o Ad Unit ID real, em produção
de verdade:
```bash
flutter build apk --dart-define=ADS_USE_TEST_AD_UNITS=false
```

### Endurecimento futuro (fora do escopo desta integração)

`POST /ads/callback` hoje aceita a confirmação vinda do próprio app
Flutter, sem nenhuma verificação criptográfica -- um cliente adulterado
poderia chamar essa rota direto, sem nunca ter mostrado nenhum anúncio
(TODO já registrado em `app/modules/ads/router.py`). O endurecimento real
é implementar a verificação servidor-a-servidor (SSV) de verdade do
Google (o próprio servidor do Google chama o backend direto, com
assinatura verificável) -- quando isso acontecer, remova a chamada
`AdsApi.confirm()` do app (marcada como temporária em
`mobile/lib/controllers/mining_controller.dart`).

## Valor de recompensa variável por sessão (seção 7)

O valor creditado ao final de cada sessão de mineração (`POST
/mining/collect`) não é mais um sorteio aleatório fixo -- vem da tabela
singleton `reward_config` (`app/models/reward_config.py`), recalculada 1x
por dia a partir do eCPM médio real do bloco de anúncios premiado no
AdMob:

```
valor_por_sessão = clamp(eCPM_médio * ADMOB_REWARD_MARGIN / 1000, R$0,01, R$1,00)
```

- **Worker diário** (`reward.update_reward_config`, agendado às 6h UTC em
  `app/workers/celery_app.py`): busca o eCPM médio do dia anterior via
  AdMob Reporting API (`app/core/admob.py`) e atualiza `reward_config`. Se a
  AdMob não tiver dado para o dia, mantém o valor vigente inalterado (não
  zera). Lógica em `app/modules/reward/service.py`.
- **Diagnóstico manual**: `GET /admin/update-reward-config` (mesma proteção
  por `ADMIN_SMOKE_TEST_TOKEN` dos outros diagnósticos) roda a mesma lógica
  na hora, sem esperar o agendamento.
- **`GET /reward/current`** (público, sem autenticação): devolve
  `value_per_session`, `avg_ecpm` e `updated_at` vigentes, para o app
  mostrar antes de minerar.
- **Onde é creditado**: continua em `collect_mining_session` (fim da sessão
  de mineração, MINING_SESSION_DURATION_SECONDS), como antes -- só o valor mudou de um sorteio aleatório para o
  valor vigente da `reward_config`. `POST /ads/callback` continua só
  confirmando o `ad_view`, sem nenhum movimento de saldo.

### Credenciais da AdMob Reporting API

A AdMob API não aceita conta de serviço pura -- precisa de um OAuth client
do Google Cloud (mesmo projeto/conta vinculado ao AdMob) e um
`refresh_token` obtido uma vez via consentimento OAuth de um usuário com
acesso à conta AdMob:

- `ADMOB_CLIENT_ID` / `ADMOB_CLIENT_SECRET`: credenciais do OAuth client
  (Google Cloud Console > APIs e Serviços > Credenciais, com a "AdMob API"
  habilitada no projeto).
- `ADMOB_REFRESH_TOKEN`: obtido uma vez via fluxo de consentimento OAuth
  (escopo `https://www.googleapis.com/auth/admob.readonly`).
- `ADMOB_PUBLISHER_ID`: ID da conta AdMob (formato `pub-XXXXXXXXXXXXXXXX`,
  painel AdMob > Configurações da conta).
- `ADMOB_AD_UNIT_ID`: Ad Unit ID **completo** do bloco premiado, mesmo
  valor usado no SDK (`ca-app-pub-9407999187872272/9926844486`, já é o
  default) -- o filtro `AD_UNIT` da Reporting API espera o ID completo, não
  só o sufixo numérico (só o sufixo é rejeitado com "Valor do filtro de
  dimensão AD_UNIT malformado").

Sem essas variáveis configuradas, o worker diário loga um aviso e mantém o
valor vigente (fail-safe); `GET /admin/update-reward-config` reporta
`{"ok": false, "error": "..."}` em vez de derrubar a rota.

### Agendamento em produção: Render Cron Job, não Celery Beat

`GET /admin/update-reward-config` roda 1x/dia em produção via um **Render
Cron Job** (`cubemine-pix-update-reward-config` em `render.yaml`,
`scripts/trigger_update_reward_config.py`, 6h UTC) -- não via o
`beat_schedule` do Celery em `app/workers/celery_app.py` (que existe no
código mas não roda de verdade em produção; nenhum Background Worker foi
deployado). Para uma única tarefa diária, um Cron Job (container efêmero,
cobrado só pelos segundos que roda, mínimo ~US$1/mês no Render) é bem mais
barato que manter um Background Worker rodando 24/7 só para o Celery Beat
checar o agendamento -- e reaproveita o mesmo endpoint admin já testado
manualmente. Cron Jobs no Render não têm tier free, mas o custo é
irrisório comparado a um worker full-time; reconsidere migrar para Celery
Beat de verdade só se surgirem várias tarefas periódicas diferentes (a
reconciliação de saques Pix, `pix.reconcile_pending_withdrawals` a cada
5min, também não roda em produção ainda -- fora do escopo desta mudança).

**Setup no Render**: depois do primeiro deploy do blueprint, cole o mesmo
valor de `ADMIN_SMOKE_TEST_TOKEN` (do serviço web) no serviço cron
`cubemine-pix-update-reward-config` -- variáveis de ambiente não são
compartilhadas automaticamente entre serviços no Render.

## Ranking

`GET /ranking` devolve dois escopos, sempre coexistindo:

- **Geral**: Top 10 de todos os usuários pelo total histórico acumulado de
  `reward` no ledger (nunca reseta -- sacar via Pix não derruba a posição de
  ninguém, ver `_lifetime_totals` em `app/modules/ranking/service.py`).
- **Regional**: Top 10 do mesmo escopo, mas só entre usuários do mesmo
  estado (Brasil) ou país (demais), detectado por IP no cadastro/login --
  `null` se o usuário ainda não tem localização detectada.

Cada escopo devolve `top` (lista ordenada) e `my_rank`/`my_total` (posição e
total do usuário autenticado, mesmo que fora do `top`).

### Apelido (`PATCH /auth/nickname`)

O ranking mostra `nickname` no lugar do e-mail (evita vazar PII na lista
pública) -- se o usuário nunca definiu um, cai no fallback `"Minerador
#<id>"`. Sem verificação de unicidade de propósito (ver `User.nickname`).

### Detecção de país/estado (GeoLite2, sem custo por requisição)

`country_code`/`state_code` (`app/models/user.py`) são preenchidos no
cadastro e reavaliados a cada login, a partir do IP do cliente
(`app/core/geoip.py`), usando o banco **GeoLite2-City da MaxMind** salvo
localmente em `GEOIP_DB_PATH` (default `geoip/GeoLite2-City.mmdb`, ignorado
pelo git -- a licença gratuita não permite redistribuir o arquivo). Preferido
a uma API HTTP de geolocalização de terceiro porque é gratuito, sem limite
de taxa e sem chamada de rede por requisição.

Sem o arquivo `.mmdb` presente, a detecção fica desligada de forma graciosa
(`country_code`/`state_code` ficam `None`) -- login/cadastro nunca falham
por causa disso.

**Setup**:
1. Crie uma conta gratuita em <https://www.maxmind.com/en/geolite2/signup> e
   gere uma license key (Minha conta > Gerenciar chaves de licença).
2. `export GEOIP_ACCOUNT_ID=... GEOIP_LICENSE_KEY=...`
3. `python scripts/download_geoip_db.py`

Em produção (Render), o mesmo script roda automaticamente no
`buildCommand` do serviço web a cada deploy (`render.yaml`), best-effort
(`|| true`) -- basta configurar `GEOIP_ACCOUNT_ID`/`GEOIP_LICENSE_KEY` no
dashboard. A MaxMind atualiza o GeoLite2 algumas vezes por mês; um app com
poucos usuários não precisa de mais que isso.

### Bônus mensal do Top 10

Todo mês, os Top 10 de cada escopo (geral + cada região com usuários
premiáveis) ganham um bônus creditado automaticamente na carteira (tipo
`bonus` no ledger), por posição:

| 1º | 2º | 3º | 4º | 5º | 6º | 7º | 8º | 9º | 10º |
|----|----|----|----|----|----|----|----|----|-----|
| R$1,00 | R$0,90 | R$0,80 | R$0,70 | R$0,60 | R$0,50 | R$0,40 | R$0,30 | R$0,20 | R$0,10 |

- Os dois escopos são independentes e **empilháveis**: um usuário no Top 10
  geral E no Top 10 do seu estado no mesmo mês recebe os dois prêmios.
- Não existe nenhum contador "do mês" para resetar -- o Top 10 mensal é
  sempre recalculado direto pela janela de datas em
  `LedgerEntry.created_at` (`_month_window`/`_monthly_totals`); o ranking
  geral (acumulado) usa uma métrica totalmente separada, então não há
  estado compartilhado para corromper.
- Idempotente por `reference_id` (`ranking-bonus-<escopo>-<AAAA-MM>-pos<N>`)
  -- rodar o job de novo no mesmo mês nunca paga a mesma posição duas vezes.
- Se o `reward_fund` não tiver saldo suficiente para uma posição específica,
  ela é pulada (reportada em `insufficient_fund` na resposta) sem travar o
  pagamento das demais -- rodar o job de novo depois de reforçar o fundo
  paga as posições que ficaram pendentes.
- Lógica em `run_monthly_ranking_payout`
  (`app/modules/ranking/service.py`); diagnóstico manual em
  `GET /admin/run-monthly-ranking-payout`; agendado em produção via Render
  Cron Job (`cubemine-pix-monthly-ranking-payout`, dia 1 de cada mês às 7h
  UTC, `scripts/trigger_monthly_ranking_payout.py`) -- mesmo padrão do Cron
  Job de `update-reward-config` acima.

### Conversão USD -> BRL do eCPM

A conta AdMob reporta o eCPM na própria moeda da conta (confirmado no
painel AdMob > Configurações > Conta: "Dólar americano (USD US$)" nesta
conta), mas a carteira do usuário é paga em Real via Pix. `ADMOB_USD_TO_BRL_RATE`
(default `5.50` em `app/core/config.py`) converte o eCPM para BRL antes de
calcular o valor por sessão -- **é uma taxa manual**, não busca câmbio ao
vivo. Atualize essa variável de vez em quando no Render conforme a cotação
real mudar; o worker não faz isso sozinho.

**TODO (fora do escopo desta integração):** este sandbox não tem acesso de
rede a `googleapis.com` para validar `networkReport:generate` contra a API
viva -- confira a documentação oficial
([developers.google.com/admob/api](https://developers.google.com/admob/api))
antes de operar em produção, especialmente o formato exato da resposta.
