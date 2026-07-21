
# CubeMine Pix — Plano Técnico Corrigido (v2)

> Este documento substitui e corrige o plano técnico anterior. Mantém o PRD original como base de produto e incorpora as correções de arquitetura identificadas na revisão técnica. Use como referência única para desenvolvimento com Claude Code / Codex — implemente **um item do roadmap por vez**, sempre citando a seção correspondente.

---

## 1. Visão geral do produto

App mobile (Android/iOS) de recompensas gamificadas. O usuário ativa um cubo virtual, assiste a um anúncio, aguarda um ciclo de "mineração" de 2h e coleta uma recompensa em reais, sacável via Pix.

**Princípio inegociável de posicionamento:** a mecânica de "mineração" é uma metáfora de jogo casual que distribui recompensas financiadas por receita real do app (anúncios, assinaturas, parcerias) — **nunca** deve ser apresentada como mineração real de criptomoeda ou como investimento com rendimento. Isso deve estar refletido tanto no texto do app quanto nos termos de uso.

**Nota não jurídica:** apps com mecânica de "aguardar → coletar → sacar em dinheiro real" têm sido escrutinados por reguladores no Brasil quando lembram esquemas de pirâmide, independentemente da intenção do criador. Vale validar com um advogado especializado em fintech/regulação do Banco Central se o modelo de saque via Pix exige alguma licença ou registro, e revisar os termos de uso antes do lançamento. A arquitetura de ledger auditável definida abaixo ajuda a demonstrar transparência, mas não substitui essa validação.

---

## 2. Stack tecnológica (decisão final)

| Camada | Escolha | Motivo |
|---|---|---|
| Frontend | Flutter | multiplataforma Android/iOS, um só código |
| Backend | Python + FastAPI | tipagem forte (Pydantic), robusto para lógica financeira |
| Banco principal | PostgreSQL | transações ACID, essencial para o ledger |
| Cache / filas | Redis | cache de saldo, broker de filas |
| Fila de jobs | Celery ou RQ (sobre Redis) | agendamento do ciclo de mineração |
| Auth | Firebase Auth | login social + e-mail/senha pronto |
| Push | Firebase Cloud Messaging | notificar fim de ciclo, saque aprovado |
| Storage | Cloud Storage (GCS/S3) | assets, imagens de cubos |
| Hospedagem | AWS ou GCP | GCP simplifica se usar Firebase |
| Monitoramento | Sentry | erros em produção |
| Analytics | Firebase Analytics | funil de uso, retenção |

---

## 3. Arquitetura do sistema

Monolito modular. Módulos isolados por domínio, prontos para virar serviços separados em v3/v4 se o volume justificar.

```

Cliente (Flutter)
   │
   ▼
API Gateway / FastAPI (REST)
   │
   ├── módulo auth       (login, registro, 2FA)
   ├── módulo wallet      (ledger, saldo, extrato)
   ├── módulo mining      (ciclo do cubo, jobs)
   ├── módulo rewards     (fundo, distribuição)
   ├── módulo ads         (integração SDK de anúncios + validação server-side)
   ├── módulo pix         (saque, webhook de status, reconciliação)
   ├── módulo referrals   (convites)
   ├── módulo missions    (missões, VIP, eventos)
   └── módulo admin       (dashboard, relatórios)
   │
   ▼
PostgreSQL (dados transacionais) + Redis (cache/filas)
```

---

## 4. Estrutura de pastas (backend)

```
backend/
├── app/
│   ├── main.py
│   ├── core/            # config, segurança, dependências
│   ├── db/               # conexão, migrations (Alembic)
│   ├── models/            # SQLAlchemy models
│   ├── schemas/           # Pydantic schemas
│   ├── modules/
│   │   ├── auth/
│   │   ├── wallet/
│   │   ├── mining/
│   │   ├── rewards/
│   │   ├── ads/
│   │   ├── pix/
│   │   ├── referrals/
│   │   ├── missions/
│   │   └── admin/
│   ├── workers/           # tasks Celery (payout, reconciliação Pix)
│   └── tests/
├── alembic/
├── requirements.txt
└── docker-compose.yml

```

---

## 5. Modelagem de banco de dados

**users**
`id, email, password_hash, phone, pix_key, kyc_status, created_at, is_blocked`

**cubes**
`id, user_id, type (comum/raro/épico/lendário/mítico), speed, bonus_chance, acquired_at`

**mining_sessions**
`id, user_id, cube_id, started_at, ends_at, status (running/collected/expired), ad_view_id`
> **Correção v2:** não existe um estado persistido `ready_to_collect`. O status "pronto para coletar" é sempre **calculado on-the-fly** (`now() >= ends_at AND status = 'running'`) no momento da chamada de `/mining/collect`, sob lock de linha. Isso elimina a corrida entre o worker que atualizaria o status e a requisição do usuário — uma única fonte de verdade.

**ledger_entries** (livro-razão — nunca um campo "saldo" solto)
`id, user_id, type (reward/withdrawal/bonus/fee), amount, reference_id, balance_after, created_at`
> Saldo do usuário = soma dos `ledger_entries`. Nunca armazenar saldo direto sem reconciliação. Pode ser cacheado no Redis, mas sempre reconciliável a partir do ledger.

**reward_fund**
`id, balance, total_in, total_out, updated_at`
> Lock transacional em toda escrita. **Nota de escala:** isso serializa toda coleta de recompensa do sistema — aceitável no MVP, mas é dívida técnica conhecida. Ao crescer, considerar orçamento aprovado em batch (atualizado a cada minuto) ou particionamento lógico do fundo, em vez de lock por transação individual.

**withdrawals**
`id, user_id, amount, pix_key, status (pending/processing/paid/failed), idempotency_key, created_at`

**ad_views**
`id, user_id, ad_network, watched_at, status (pending/confirmed/rejected)`
> **Correção v2:** o registro é criado como `pending` quando o cliente avisa que assistiu (`POST /ads/watch`). A mineração só pode iniciar depois que o **callback assíncrono do SDK** (verificação server-to-server, ex: SSV do AdMob) confirma o registro como `confirmed`. Nunca liberar o início do ciclo apenas com base no aviso do cliente — é exatamente o ponto que a validação deveria proteger.

**missions / vip_levels / events / referrals**
tabelas de apoio, cada uma com `user_id` + status + recompensa associada, todas gerando entradas em `ledger_entries` quando pagam algo.

**admin_logs**
`id, admin_id, action, target_id, created_at` — toda ação administrativa fica registrada.

---

## 6. Sistema de carteira (ledger) — detalhe crítico

1. Toda movimentação financeira (recompensa, saque, bônus, taxa) vira uma linha **imutável** em `ledger_entries`.
2. O saldo disponível é a soma de todas as entradas do usuário (cacheável no Redis, sempre reconciliável a partir do ledger).
3. Saque: cria uma entrada `withdrawal` com status `pending`, só é debitada quando o status vira `paid`.
4. Toda operação que mexe em saldo passa por transação de banco com `SELECT FOR UPDATE`, evitando corrida em requisições simultâneas.

---

## 7. Ciclo de mineração — fluxo técnico corrigido

1. Usuário assiste anúncio → app envia confirmação ao backend (`POST /ads/watch`) → cria `ad_views` com status `pending`.
2. Backend aguarda o **callback assíncrono do SDK** de anúncios confirmando a visualização → atualiza `ad_views.status = confirmed`.
3. Somente após confirmação, o cliente pode chamar `POST /mining/start`, que cria `mining_session` com `started_at = now()`, `ends_at = now() + 2h`, `status = running`.
4. Um worker assíncrono (Celery/RQ) apenas **agenda um lembrete** (push notification) para `ends_at` — ele não é a fonte de verdade do status da sessão.
5. Usuário chama `POST /mining/collect` com **chave de idempotência obrigatória**. O backend, sob lock de linha, calcula `now() >= ends_at` diretamente — não confia em nenhum campo de status pré-calculado.
6. Backend sorteia a recompensa dentro das regras do fundo (com lock transacional no `reward_fund`, nunca deixando o fundo negativo), grava em `ledger_entries`, marca a sessão como `collected`.

---

## 8. Fundo de recompensas

- Toda entrada (receita de ads, assinatura, parceria) e saída (payouts) do fundo é lançada em `reward_fund` com lock transacional.
- Sorteio de recompensa deve respeitar: `soma_esperada_de_payouts <= fundo.balance * margem_de_segurança`.
- Dashboard admin mostra saldo do fundo em tempo real e alerta quando estiver abaixo de um limite configurável.
- Ver nota de escala na seção 5 sobre o lock virar gargalo em alto volume.

---

## 9. Endpoints principais (REST)

```

POST   /auth/register
POST   /auth/login
POST   /auth/2fa/verify

GET    /wallet/balance
GET    /wallet/statement

POST   /ads/watch              → cria ad_view pending
POST   /ads/callback           → webhook do SDK, confirma ad_view
POST   /mining/start           → exige ad_view confirmado
GET    /mining/status          → calculado on-the-fly, nunca persistido
POST   /mining/collect         (idempotency-key obrigatório)

POST   /pix/withdraw           (idempotency-key obrigatório)
GET    /pix/withdrawals
POST   /pix/webhook            → confirmação do PSP

POST   /referrals/invite
GET    /referrals/stats

GET    /missions
POST   /missions/{id}/claim

GET    /admin/dashboard
GET    /admin/fund
POST   /admin/withdrawals/{id}/approve
```

---

## 10. Segurança e anti-fraude (desde o MVP)

- Rate limiting por IP e por device (ex: `slowapi` no FastAPI).
- 2FA obrigatório para saque acima de um valor configurável.
- Verificação de identidade (KYC leve) para saques recorrentes ou de valor alto.
- Fingerprint básico de device para detectar múltiplas contas no mesmo aparelho.
- Validação server-side do anúncio assistido via callback do SDK — nunca confiar apenas no cliente.
- Logs de auditoria em toda ação de saldo/saque.

---

## 11. Integração Pix

- Usar um PSP (provedor de pagamento) com API de "Pix out" regulamentada no Brasil.
- Fluxo: `withdrawal.pending` → chamada ao PSP → webhook de confirmação → `withdrawal.paid` + lançamento no ledger.
- Todo saque tem `idempotency_key` única para evitar pagamento duplicado em retries.
- **Correção v2 — reconciliação:** webhooks podem chegar fora de ordem, duplicados ou nunca chegar. Adicionar um worker periódico que consulta o status real no PSP para todo saque parado em `processing` há mais de X minutos, em vez de depender só do webhook.

---

## 12. Roadmap de implementação

**Fase 1 — MVP**
1. Setup do projeto (FastAPI + PostgreSQL + Alembic + Docker Compose)
2. Módulo auth (Firebase Auth + endpoints)
3. Modelagem do banco (users, cubes, mining_sessions, ad_views, ledger_entries, reward_fund)
4. Módulo wallet (ledger + saldo)
5. Módulo ads (registro pending + callback de confirmação do SDK)
6. Módulo mining (ciclo completo com status calculado on-the-fly + idempotência na coleta)
7. Frontend Flutter: telas de cadastro, login, tela do cubo, carteira
8. Testes do fluxo completo ponta a ponta, incluindo cenários de retry/duplicidade

**Fase 2**
9. Módulo pix (saque + integração PSP + worker de reconciliação)
10. Painel admin básico (usuários, saques, fundo)
11. Anti-fraude inicial (rate limit, device fingerprint)

**Fase 3**
12. Missões, VIP, ranking, convites
13. Assinaturas premium
14. Painel admin completo (relatórios, logs)

**Fase 4**
15. Eventos especiais, cubos raros
16. Expansão internacional / multi-moeda

---

## 13. Como usar este documento no Claude Code

Peça para implementar **um item do roadmap por vez**, sempre referenciando a seção correspondente (ex: "implemente o módulo `mining` conforme a seção 7 e o schema da seção 5, respeitando a correção v2 de status calculado on-the-fly"). Isso mantém o contexto pequeno e o código consistente com as decisões de arquitetura aqui definidas.
```
