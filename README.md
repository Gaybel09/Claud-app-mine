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
envio de Pix disparado é real, contra o ambiente sandbox da Efí.

O saque de teste sempre vai para `efipay@sejaefi.com.br` (chave `favorecido`,
constante `EFI_SANDBOX_HOMOLOGATION_PIX_KEY` em `smoke_test.py`) -- nunca
para `EFI_PAYER_PIX_KEY` nem qualquer outra configuração. É a chave oficial
de homologação da Efí ([dev.efipay.com.br/docs/api-pix/envio-pagamento-pix](https://dev.efipay.com.br/docs/api-pix/envio-pagamento-pix),
seção "Instruções para testes em Homologação"): em sandbox, só saques para
EXATAMENTE essa chave são confirmados/rejeitados de verdade (valores entre
R$0,01 e R$10,00, faixa em que `mining.MIN_REWARD`/`MAX_REWARD` sempre
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
sem esperar o agendamento do Celery Beat (5min) nem o corte de
`RECONCILE_AFTER_MINUTES` (10min). Útil pra confirmar que o fluxo funciona
só com a reconciliação, sem depender do webhook receber corretamente (ex:
mTLS de recebimento não é viável no plano gratuito do Render). Adiciona uma
etapa `pix_reconcile` com `status_before`/`status_after`/`failure_reason`,
mostrando a transição de status do saque causada pela consulta real à Efí
(`GET /v2/gn/pix/enviados/id-envio/:idEnvio`).

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
confirmação é 100% automático -- via webhook (`POST /pix/webhook`) ou, se
ele não chegar, via reconciliação periódica (`pix.reconcile_pending_withdrawals`,
a cada 5min, para saques parados em `processing` há mais de
`RECONCILE_AFTER_MINUTES`). Este endpoint é só a via de escape manual para
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
| `POST /mining/collect` | 30/min | 10/min | Coleta deveria acontecer ~1x por ciclo (2h); limita spam de polling/tentativas de abusar do lock de linha |
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

### ⚠️ `ADS_DEV_AUTO_CONFIRM` (backend, `app/core/config.py`)

O app já confirma o `ad_view` sozinho depois de assistir o anúncio de
verdade (acima) -- não precisa mais desta flag pra testar o app
interativamente. Ela continua existindo só para cenários **sem** o app
rodando (testes automatizados, diagnóstico do backend como
`admin/smoke_test.py`), onde não há RewardedAd nenhum pra assistir: com
`true`, `POST /ads/watch` confirma o `ad_view` sozinho, sem esperar
`POST /ads/callback`.

**Default `false` (fail-safe) e precisa continuar assim em qualquer deploy
de produção de verdade.** Sem uma confirmação real de que o anúncio foi
assistido até o fim (seja pelo app com o SDK real, seja por uma futura
verificação servidor-a-servidor), essa flag destrava mineração de graça
pra qualquer usuário -- falha de segurança grave, não só um bug de
desenvolvimento.

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
