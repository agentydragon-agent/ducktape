# Plaid MCP: self-contained links + SQL-over-synced-Postgres read path

_Draft plan, 2026-05-30._

## Context

Today a Plaid link is represented across **four** hand-edited places to add one institution:

- airlock `config.yaml`: a per-bank OAuth provider stanza (`plaid_chase`, `plaid_bofa`) with its
  own `redirect_uri` → one **Plaid dashboard redirect URI per bank**.
- airlock deployment: duplicated `PLAID_<BANK>_CLIENT_ID/SECRET` env.
- plaid-mcp `external-secret.yaml`: a per-bank ESO mirror of the access-token Secret from airlock's
  namespace.
- plaid-mcp `items.yaml`: a static registry row.

The read path already supports multiple items, so the pain is **provisioning**, not runtime. Goals:

1. Make link management **dynamic + self-contained** on the Plaid web service — browser UI to
   add/remove/repair links, one shared redirect URI. This is in v0; bespoke MCP tools are not.
2. Fold airlock's **Plaid** OAuth in (removes the cross-namespace ESO hop + duplicate registry).
   airlock keeps its other roles (approval proxy + google/oura/bsc OAuth); only its Plaid goes.
3. Sync all Plaid data (incl. investments) into **Postgres**, and give the agent an **off-the-shelf
   read-only Postgres MCP** over it — arbitrary SQL is far more flexible than a fixed tool set.
   Access tokens stay in **k8s Secrets** (never in PG), so a read-only DB role is safe to expose.

Unblocks linking **Interactive Brokers + Wealthfront** (investments-capable) next to the two
existing bank links. (Coinbase is out — Plaid doesn't aggregate it.)

## Locked decisions

- **Reads = off-the-shelf read-only Postgres MCP over the synced DB.** Use
  `enterprisedb/pg-airman-mcp` in `--access-mode=restricted` (read-only) on **streamable-HTTP**
  transport. The agent reads all Plaid data via SQL; no bespoke read tools. (Avoid the deprecated
  `@modelcontextprotocol/server-postgres` — known read-only-bypass SQLi.)
- **v0 has a Plaid web service but no bespoke Plaid MCP tools**: `/link` handles add/remove/repair and
  writes access-token Secrets; a sync CronJob writes Postgres; the agent-facing read interface is only
  the read-only Postgres MCP.
- **v1 bespoke MCP = non-DB ops only**: optional `get_live_balance` (real-time Plaid) and
  `sync_link`/`sync_all` (trigger sync). Add/remove/repair are **`/link` UI only**, not tools. No
  `dump_all`, no net-worth-history tool — SQL covers ad-hoc aggregation.
- **v1 exposes two MCP endpoints, each behind its own `mcp-oauth-facade`** (no compositor for now):
  the bespoke Plaid server keeps `plaid-mcp.allegedly.works` (+ `plaid-mcp-oidc` app); the Postgres
  MCP gets its own facade + HTTPRoute (`plaid-db.allegedly.works`) and a new Authentik app
  (`plaid-db-mcp-oidc`, restricted to agentydragon). The agent adds both servers. Both Deployments
  live in the `plaid-mcp` namespace and share the one CNPG cluster (writer vs `plaid_ro` roles).
- **v0 exposes two HTTP surfaces but only one MCP surface**: `plaid-mcp.allegedly.works` serves the
  human `/link` UI/callbacks; `plaid-db.allegedly.works` serves the Postgres MCP. There are no v0
  bespoke Plaid MCP tools.
- **Storage split**: synced data in **CNPG Postgres**; each access token in its **own k8s Secret**
  (server writes via the k8s API). **Two DB roles**: owner (writer, used by sync) + `plaid_ro`
  (`GRANT SELECT` only, used by the Postgres MCP) — defense-in-depth atop the MCP's restricted mode.
- **v0 sync is synchronous full-refresh**: for a small personal link set, start with a blocking
  internal sync engine / Cron entrypoint that fetches the configured Plaid windows and reconciles the
  local DB to match. Target "fresh within 12h" data, not real-time. Skip automatic real-time
  `/accounts/balance/get` in v0; cached balances from Plaid product responses are acceptable.
- **v1 sync follows Plaid's product-specific update contracts**: Transactions use cursor
  `/transactions/sync`; holdings/liabilities are current-state snapshots; investment transactions are
  date-range + offset paginated. Webhooks trigger prompt sync, and Cron is a backstop.
- **Link creation is product-intent-first**: `/link` asks what data surface is being connected
  before creating a Plaid `link_token`. The server maps that intent to Plaid product params; repair
  and later expansion use update mode. Do not default every link to every product, because requested
  products affect institution/account availability and billing.

## Target data model

Postgres via async SQLAlchemy ORM + Alembic (mirror `airlock/storage.py`). The ORM (owner role)
defines tables; `plaid_ro` gets `SELECT`. Migrations must add `COMMENT ON` descriptions for every
table, view, and non-obvious column so the Postgres MCP's schema introspection gives the agent useful
context without needing to read source code.

Base tables should stay close to Plaid's own response shapes: use Plaid object names, IDs, field names,
and endpoint boundaries wherever practical (`item_id`, `account_id`, `transaction_id`,
`pending_transaction_id`, `iso_currency_code`, etc.). Do not build a bespoke accounting/net-worth
domain model into the storage tables. Put agent-friendly interpretation, filtering, and aggregation in
documented SQL views.

- `links` (PK `item_id`): institution_id/name, label, link_profile, products_requested/
  products_authorized/products_billed,
  status (active/login_required/pending_expiration/revoked), access_token_secret (k8s Secret name),
  transactions_cursor, transactions_update_status, created/updated/last_synced_at.
- `accounts` (PK account_id, FK item_id): name/official_name/mask/type/subtype/currency.
- `transactions` (PK transaction_id): account/item FK, date, amount, name, merchant, pending,
  pending_transaction_id, PFC primary/detailed, removed, removed_at. Never hard-delete transactions;
  pending authorizations can disappear or be replaced by posted transactions, and posted transactions
  can still be modified later.
- `balance_snapshots`: account FK, captured_at, available/current/limit/currency.
- `securities` (PK security_id): name/ticker/type/currency.
- `holding_snapshots`: account+security FK, captured_at, quantity/cost_basis/price/value.
- `investment_transactions` (PK): account/security FK, date/amount/quantity/price/fees/type/subtype.
- `liability_{credit,mortgage,student}_snapshots`: account FK, captured_at, fields already in
  `plaid_utils/models.py` (APRs, statement/payment dates, rates, payoff).
- `sync_runs` (append-only): run_id, trigger (cron/link/manual), mode (v0_full_refresh/v1_incremental),
  item_id nullable for per-link runs, configured windows, status, started_at/finished_at, error summary.
  Use this for operator/debug visibility and to correlate API events.
- `plaid_api_events` (append-only): endpoint, item/account context when known, request_id, status,
  duration, error code/type, sync_run_id when known, redacted request JSON, redacted response JSON,
  created_at. Redact `access_token`, `public_token`, client secrets, and headers before writing. This
  is for audit and debugging; it is not the source of truth for queryable financial state.
- Derived SQL views are allowed for convenience (`current_transactions`, `latest_balances`,
  `latest_holdings`, `account_product_status`, etc.), but they must not replace the Plaid-shaped base
  rows.

**Capabilities**: a `Product` `StrEnum`; `links.products_*` typed sets; sync + tools gate on them.
Store the human-facing `link_profile` that produced the Plaid params so the UI can explain why a
link has particular scopes. Add an `account_product_status` SQL view (or materialized table if needed)
that maps each account to available synced surfaces: transactions, balance snapshots, holdings,
investment transactions, and liability snapshots; comment the view and its columns with plain-language
guidance for agent SQL. Reuse the discriminated-union pattern
(`airlock/oauth/provider.py:41-61`, `airlock/models.py:93-95`) for link-status / relink-reason
(repair vs add-scope).

## Agent interface

v0:

1. **Postgres MCP — `plaid-db.allegedly.works` (off-the-shelf, read-only)** — the only agent-facing
   MCP interface. The web UI creates/repairs/removes links, the CronJob syncs Plaid into Postgres, and
   the agent issues SQL against
   links/accounts/transactions/holdings/investment_transactions/liabilities/snapshots.
2. **Plaid web UI — `plaid-mcp.allegedly.works/link`** — human-only link management. It is not exposed
   as MCP and does not provide agent read tools.

v1:

3. **Plaid MCP tools — `plaid-mcp.allegedly.works` (bespoke)** — optional non-DB ops only:
   - `get_live_balance(link, account=None)` — real-time, rate-limited, hits Plaid directly.
   - `sync_link(link)` / `sync_all()` — on-demand run of the cron's sync engine.

## Link lifecycle / UI (lift from airlock)

- **Choose data surface first**: `/link` starts with product-profile controls before creating the
  Plaid token. Initial profiles:
  - `cashflow`: checking/savings/credit-card transaction history (`transactions`; Balance is implicit
    once another product is initialized).
  - `credit_card_detail`: credit-card terms/payment metadata (`liabilities`) plus optional spending
    history (`transactions`).
  - `investments_holdings`: investment accounts and positions (`investments`, holdings sync only).
  - `investments_full`: holdings plus investment transaction history (`investments`, and call
    `/investments/transactions/get` only for links that selected it).
  - `full_picture`: transactions + investments + liabilities where supported.
  - `advanced`: raw Plaid product checkboxes for unusual cases. The normal UI should present
    account/data intents, not Plaid API names.
- **Add**: `/link` mints a `link_token` (one shared
  `redirect_uri https://plaid-mcp.allegedly.works/link/callback`), renders Plaid Link JS;
  `onSuccess` POSTs `public_token` → exchange → write access-token Secret + insert `links` row →
  initial sync.
- **Repair / add-scope**: Plaid **update mode** (`link_token` with `access_token`, plus extra
  `products`). One path, reason attached. `/item/get` `available_products` vs `billed_products`
  drives the "you could add investments" affordance.
- **Remove**: a `/link` UI button → `/item/remove`, delete the access-token Secret, mark row
  `revoked`. Not an MCP tool.

Reuse: `airlock/oauth/provider.py` (`PlaidProvider.create_link_token`/`exchange_public_token`),
`airlock/oauth/routes.py`, `airlock/oauth/k8s_client.py` (`K8sTokenStore` → adapt to a small
`secret_store.py`), `airlock/app.py:74-120` (FastAPI mounting FastMCP + custom routes + SPA),
`airlock/frontend/OAuthProviders.svelte` (Link widget).

## Sync engine

### v0: synchronous full-refresh mirror

v0 favors a small, understandable implementation over cursor/webhook complexity. The web app and
CronJob share a blocking sync engine; "sync one link" and "sync all links" are internal entrypoints,
not MCP tools. A CronJob runs at least every 12 hours; the web app may trigger the same engine after
link/add-scope repair so newly-linked data is available quickly.

Use Postgres advisory locks or a `sync_runs` state guard so Cron and link-triggered sync cannot refresh
the same Item concurrently. Full-refresh windows are explicit config, persisted on each `sync_runs` row,
and used for reconciliation boundaries; never mark rows outside the refreshed window as removed.

Per link (writer role):

1. `/item/get`: refresh status, products, billed_products, available_products, and Item freshness
   metadata. `ITEM_LOGIN_REQUIRED` → `status=login_required` (UI shows "repair").
2. `/accounts/get`: upsert Plaid account objects and cached balances. Do not call
   `/accounts/balance/get` automatically in v0. v1 can expose `get_live_balance` as the explicit
   real-time balance path.
3. `transactions`: fetch the configured history window without relying on a cursor. Upsert every
   returned transaction by Plaid `transaction_id`; for previously-seen transactions inside the same
   link/window that are absent from the fresh response, mark `removed=true`/`removed_at` rather than
   hard-deleting. This keeps pending disappearance and pending-to-posted replacement auditable.
4. `investments_holdings`: fetch full current holdings/securities; upsert securities and append a
   timestamped holding snapshot batch.
5. `investment_transactions`: fetch the configured date window with `count`/`offset` pagination and
   upsert by Plaid investment transaction ID. If we add a `removed` marker for investment transactions,
   reconcile absence only within the refreshed window.
6. `liabilities`: fetch current liability data and append timestamped liability snapshots.
7. Every Plaid request passes through one client wrapper that writes a `plaid_api_events` row in the
   same database transaction as the state update where practical, or immediately after the response/error
   otherwise. The wrapper logs request/response metadata and redacted JSON, never access tokens or
   secrets.

v0 deliberately does not implement transaction cursors, Plaid webhook ingestion, job queues, or
`TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` recovery. The schema still includes cursor/status fields
so v1 can be added without a storage migration that rewrites existing rows.

### v1: Plaid-recommended incremental semantics

Sources to encode in tests: Plaid Transactions Sync, Transaction states, Transaction webhooks,
Investments API, Liabilities API, Accounts/Balance docs, and webhook verification docs:

- <https://plaid.com/docs/transactions/sync-migration/>
- <https://plaid.com/docs/transactions/transactions-data/>
- <https://plaid.com/docs/transactions/webhooks/>
- <https://plaid.com/docs/api/products/investments/>
- <https://plaid.com/docs/api/products/liabilities/>
- <https://plaid.com/docs/api/accounts/>
- <https://plaid.com/docs/api/webhooks/webhook-verification/>

Per link (writer role):

1. `/item/get`: refresh status, products, billed_products, available_products, and Item freshness
   metadata. `ITEM_LOGIN_REQUIRED` → `status=login_required` (UI shows "repair").
2. **Transactions**: use `/transactions/sync`, not `/transactions/get`.
   - Keep one cursor per Item unless we intentionally introduce per-account cursors; do not mix an
     Item-level cursor with `account_id`-filtered sync calls.
   - Initial sync uses a null cursor. Use `cursor="now"` only for a documented migration from an
     existing `/transactions/get` store, not for new Items.
   - Loop while `has_more`; accumulate `added`, `modified`, and `removed` across all pages.
   - Apply all accumulated updates in one DB transaction: upsert `added`, upsert `modified`, mark
     `removed=true`/`removed_at` for removed transaction IDs, then persist `next_cursor` only after
     the data changes commit.
   - If Plaid returns `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`, discard the partial page set
     and restart from the cursor used for the first page of that loop.
   - Treat pending transactions as provisional. When a pending transaction posts, Plaid may return the
     pending ID in `removed` and the posted transaction in `added`; use `pending_transaction_id` to
     relate them when present, but do not assume every pending transaction has a posted match.
   - Do not assume posted transactions are immutable. Always apply future `modified` and `removed`
     updates surfaced by `/transactions/sync`.
3. **Transaction webhooks**: configure the Plaid `webhook` URL in `/link/token/create`. After the
   first `/transactions/sync` call for an Item, handle `SYNC_UPDATES_AVAILABLE` by enqueueing a sync
   for that Item. Cron still runs as a missed-webhook/backfill safety net.
4. **Accounts/balances**: for regular account metadata, `/accounts/get` is cached and free; for
   snapshots requiring fresh balances, `/accounts/balance/get` is real-time, higher-latency, and paid.
   Keep `get_live_balance` on `/accounts/balance/get`; make any Cron balance snapshot use of that
   endpoint explicit and rate-limited.
5. **Investments**:
   - `/investments/holdings/get` returns current holdings/securities; write timestamped holding
     snapshots and upsert securities.
   - `/investments/transactions/get` is not cursor-delta based. Initial backfill fetches the configured
     history window (up to Plaid's supported 24 months) using `count`/`offset` pagination and upserts
     by Plaid investment transaction ID. Recurring sync refetches an overlapping recent window and
     upserts; a less frequent full-window reconciliation can repair missed or changed rows.
   - Handle `HOLDINGS: DEFAULT_UPDATE`, `INVESTMENTS_TRANSACTIONS: DEFAULT_UPDATE`, and
     `INVESTMENTS_TRANSACTIONS: HISTORICAL_UPDATE` webhooks by enqueueing the relevant investment
     sync.
6. **Liabilities**: `/liabilities/get` returns the latest current-state liability data, refreshed by
   Plaid roughly daily. On Cron or `LIABILITIES: DEFAULT_UPDATE`, fetch and append liability snapshots;
   do not invent transaction-like delta semantics.
7. **Webhook receiver**: expose a Plaid webhook route outside the MCP OAuth facade path, verify the
   `Plaid-Verification` JWT using `/webhook_verification_key/get`, reject stale or hash-mismatched
   payloads, persist a small audit row, and enqueue sync work idempotently.

**New** Plaid models + endpoints for investments (absent from `plaid_utils/models.py`).

## Deployment / k8s

v0 in `cluster/k8s/agents/plaid-mcp/`:

- **plaid-web** (bespoke app, existing `app/`): FastAPI + static/Svelte UI, no MCP tools exposed in
  v0. Serves `/link` and `/link/callback` at `plaid-mcp.allegedly.works`, exchanges public tokens,
  writes access-token Secrets, inserts/updates `links`, supports repair/add-scope/remove, and can kick
  off the same synchronous sync engine after successful link.
- **plaid-sync CronJob**: image's `sync` entrypoint, writer `DATABASE_URL` from the CNPG `-app`
  secret, Plaid client credentials, and read access to access-token Secrets. This is not an MCP server.
- **plaid-db-mcp**: `enterprisedb/pg-airman-mcp --access-mode=restricted
--transport=streamable-http` + its own facade → `plaid-db.allegedly.works`. Reader
  `DATABASE_URL` from `plaid-mcp-db-readonly`. New Authentik app `plaid-db-mcp-oidc`
  (Terraform `agent-machine-access`, restricted to agentydragon), own Service + HTTPRoute +
  ConfigMap + CiliumNetworkPolicy mirroring the bespoke one.

CNPG `plaid-mcp-db` + read-only role (mirror `cluster/k8s/study-casino/db/`):

- `postgres-cluster.yaml` with
  `managed.roles: [{name: plaid_ro, login: true, passwordSecret: plaid-mcp-db-readonly}]`.
- `readonly-role-provisioner-job.yaml` + `readonly-role.sql` ConfigMap (`GRANT SELECT` on all
  tables + `ALTER DEFAULT PRIVILEGES`), run as the app owner.
- `readonly-secret.sops.yaml` (`plaid-mcp-db-readonly`: username/password/DATABASE_URL).

v1 additions:

- **plaid-mcp tools**: mount FastMCP on the existing Plaid web app and expose only non-DB operations:
  `get_live_balance`, `sync_link`, and `sync_all`.

Other:

- **Delete** `items.yaml` + the per-token `external-secret.yaml` mirrors. Provide
  `plaid-client-credentials` directly in the `plaid-mcp` ns (relocate the SOPS file).
- **airlock**: drop `plaid_chase`/`plaid_bofa` from `config.yaml`, drop `PLAID_*` env, delete its
  Plaid provider code. (airlock otherwise unchanged.)

## Migration (parallel stand-up → cutover)

1. Deploy `plaid-mcp-db`, `plaid-web`, `plaid-db-mcp`, and the sync CronJob alongside the running
   setup.
2. Backfill: for each existing token (`plaid-chase-access-token`, `plaid-bofa-access-token`) call
   `/item/get` from the sync/bootstrap command → insert a `links` row, keep the Secret in the
   `plaid-mcp` ns. Run an initial full sync.
3. Add the new `plaid-db.allegedly.works` Postgres MCP and confirm SQL reads work.
4. Decommission airlock's Plaid providers + the ESO mirrors + `items.yaml`.
5. Link **Interactive Brokers + Wealthfront** through the v0 `/link` UI.
6. v1: optionally mount the bespoke Plaid MCP tools for live balance and manual sync triggers.

## Critical files

- `plaid_utils/`: `models.py` (+investments/liabilities Plaid models), new `link_store.py`
  (SQLAlchemy ORM + Alembic), `plaid_link.py` (link_token/exchange, from airlock), `secret_store.py`
  (k8s Secret writer), `sync.py` (engine), `mcp_server/server.py` (deferred v1: shrinks to 3 tools),
  `mcp_server/app.py` (v0 FastAPI `/link` + `/link/callback`; v1 optional MCP mount),
  `mcp_server/web/`
  (Link UI), `README.md` (document product profiles, sync contracts, schema/query guidance),
  `BUILD.bazel` (+ `sync` binary, + frontend).
- `cluster/k8s/agents/plaid-mcp/`: new `db/` (`postgres-cluster.yaml`,
  `readonly-role-provisioner-job.yaml`, `readonly-role.sql` CM, `readonly-secret.sops.yaml`);
  `app/` adds `rbac.yaml` + `cronjob.yaml`, edits `deployment.yaml` (writer env, SA) +
  `configmap.yaml`; delete `items.yaml`, per-token `external-secret.yaml`.
- `cluster/k8s/agents/plaid-db-mcp/` (new): `deployment.yaml` (Pg Airman MCP + facade),
  `service.yaml`, `httproute.yaml` (`plaid-db.allegedly.works`), `configmap.yaml` (facade →
  localhost upstream), `ciliumnetworkpolicy.yaml`; OIDC app `plaid-db-mcp-oidc` via Terraform.
- `cluster/k8s/agents/airlock/`: `config.yaml`, `deployment.yaml` (drop Plaid).

## Documentation requirements

- Update `plaid_utils/README.md` with the operational sync contract:
  product-profile selection, v0 full-refresh behavior, Plaid endpoint used per product, v1
  cursor/webhook behavior, pending vs posted transaction semantics, how removed rows are represented,
  and Cron vs webhook responsibilities.
- Include direct links to the Plaid docs that define each behavior, especially Transactions Sync,
  Transaction states, Investments, Liabilities, Accounts/Balance, and webhook verification.
- Document the SQL-facing model for agents: which tables are append-only snapshots, which rows are
  current-state upserts, which views to prefer for common questions, and how to filter out removed
  transactions.
- Document that base tables intentionally mirror Plaid objects and endpoint shapes; semantic rollups
  belong in views so future Plaid fields/products can be added without reworking the core schema.
- Document the Plaid API audit log: what is captured, what is redacted, retention expectations, and why
  the audit log is separate from queryable state tables.
- Document sync windows, overlap/concurrency behavior, and how `sync_runs` correlates with
  `plaid_api_events`.
- Alembic migrations must include `COMMENT ON TABLE`, `COMMENT ON VIEW`, and useful
  `COMMENT ON COLUMN` statements. Comments should explain semantics and caveats, not just restate
  names; for example, `transactions.removed` should mention Plaid removed updates and pending-to-posted
  replacement behavior.

## Verification

- `bbr test //plaid_utils/...` — `FakePlaidApi` gains investments/liabilities.
- v0 tests: `link_store` CRUD; product-profile gating; synchronous full refresh; transaction upsert
  and absent-in-window `removed` marking; pending-to-posted replacement via full-window reconciliation;
  investment transaction pagination; holding/liability snapshot writes; Plaid API audit-log redaction;
  `sync_runs` recording / same-Item concurrency guard; and the add/exchange path.
- v1 tests when incremental sync lands: cursor advance, delta apply, cursor commit ordering,
  `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` restart, and webhook verification/enqueueing.
- Read-only enforcement: a test that the `plaid_ro` role rejects writes (INSERT/UPDATE fails) while
  SELECT works.
- Sandbox: extend `plaid_utils/sandbox_smoke.py` to create a sandbox Item via the new exchange path,
  run a full sync, assert rows in every table.
- Live: deploy; open `/link`, add an institution → assert `links` row + k8s Secret created;
  link-triggered initial sync or the sync CronJob runs, then SQL via the Postgres MCP
  (`plaid-db.allegedly.works`) returns
  holdings/transactions; trigger the CronJob (`kubectl create job --from=cronjob/plaid-mcp-sync`);
  use the `/link` remove button → assert `/item/remove` called + Secret deleted + row `revoked`.
- v1 live: after mounting bespoke Plaid MCP tools, assert `get_live_balance` and manual `sync_*`
  work.

## Out of scope

- Coinbase aggregation (unsupported by Plaid).
- Per-link distinct Plaid apps (single shared client_id/secret is correct).
