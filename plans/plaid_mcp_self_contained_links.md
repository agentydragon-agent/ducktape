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

1. Make link management **dynamic + self-contained** on the Plaid MCP server — a browser UI to
   add/remove/repair links, one shared redirect URI.
2. Fold airlock's **Plaid** OAuth in (removes the cross-namespace ESO hop + duplicate registry).
   airlock keeps its other roles (approval proxy + google/oura/bsc OAuth); only its Plaid goes.
3. Sync all Plaid data (incl. investments) into **Postgres**, and give the agent an **off-the-shelf
   read-only Postgres MCP** over it — arbitrary SQL is far more flexible than a fixed tool set.
   Access tokens stay in **k8s Secrets** (never in PG), so a read-only DB role is safe to expose.

Unblocks linking **Interactive Brokers + Wealthfront** (investments-capable) next to the two
existing bank links. (Coinbase is out — Plaid doesn't aggregate it.)

## Locked decisions

- **Reads = off-the-shelf read-only Postgres MCP over the synced DB.** Recommend
  `crystaldba/postgres-mcp` in `--access-mode=restricted` (read-only) on **streamable-HTTP**
  transport (Docker image, actively maintained). The agent reads all Plaid data via SQL; no
  bespoke read tools. (Avoid the deprecated `@modelcontextprotocol/server-postgres` — known
  read-only-bypass SQLi.)
- **Bespoke MCP = non-DB ops only**: `get_live_balance` (real-time Plaid), `sync_link`/`sync_all`
  (trigger sync). Add/remove/repair are **`/link` UI only**, not tools. No `dump_all`, no
  net-worth-history tool — SQL covers ad-hoc aggregation.
- **Two separate MCP endpoints, each behind its own `mcp-oauth-facade`** (no compositor for now):
  the bespoke Plaid server keeps `plaid-mcp.allegedly.works` (+ `plaid-mcp-oidc` app); the Postgres
  MCP gets its own facade + HTTPRoute (`plaid-db.allegedly.works`) and a new Authentik app
  (`plaid-db-mcp-oidc`, restricted to agentydragon). The agent adds both servers. Both Deployments
  live in the `plaid-mcp` namespace and share the one CNPG cluster (writer vs `plaid_ro` roles).
- **Storage split**: synced data in **CNPG Postgres**; each access token in its **own k8s Secret**
  (server writes via the k8s API). **Two DB roles**: owner (writer, used by sync) + `plaid_ro`
  (`GRANT SELECT` only, used by the Postgres MCP) — defense-in-depth atop the MCP's restricted mode.
- **Transactions** via cursor `/transactions/sync` → accumulated table. **Cron** syncs all links;
  each sync writes timestamped balance/holding/liability rows (append-only; latest is what reads use).

## Target data model

Postgres via async SQLAlchemy ORM + Alembic (mirror `airlock/storage.py`). The ORM (owner role)
defines tables; `plaid_ro` gets `SELECT`. Add `COMMENT ON` to tables/columns so the Postgres MCP's
schema introspection gives the agent good context.

- `links` (PK `item_id`): institution_id/name, label, products_requested/billed,
  status (active/login_required/pending_expiration/revoked), access_token_secret (k8s Secret name),
  transactions_cursor, created/updated/last_synced_at.
- `accounts` (PK account_id, FK item_id): name/official_name/mask/type/subtype/currency.
- `transactions` (PK transaction_id): account/item FK, date, amount, name, merchant, pending,
  pending_transaction_id, PFC primary/detailed, removed.
- `balance_snapshots`: account FK, captured_at, available/current/limit/currency.
- `securities` (PK security_id): name/ticker/type/currency.
- `holding_snapshots`: account+security FK, captured_at, quantity/cost_basis/price/value.
- `investment_transactions` (PK): account/security FK, date/amount/quantity/price/fees/type/subtype.
- `liability_{credit,mortgage,student}_snapshots`: account FK, captured_at, fields already in
  `plaid_utils/models.py` (APRs, statement/payment dates, rates, payoff).

**Capabilities**: a `Product` `StrEnum`; `links.products_*` typed sets; sync + tools gate on them.
Reuse the discriminated-union pattern (`airlock/oauth/provider.py:41-61`, `airlock/models.py:93-95`)
for link-status / relink-reason (repair vs add-scope).

## Agent interface (two separate MCP servers)

The agent connects to both:

1. **Postgres MCP — `plaid-db.allegedly.works` (off-the-shelf, read-only)** — primary data
   interface. The agent issues SQL against the synced DB (links/accounts/transactions/holdings/
   investment_transactions/liabilities/snapshots). Replaces bespoke `list_items`/`list_accounts`/
   `list_transactions`/`get_liabilities`.
2. **Plaid MCP — `plaid-mcp.allegedly.works` (bespoke)** — non-DB ops only:
   - `get_live_balance(link, account=None)` — real-time, rate-limited, hits Plaid directly.
   - `sync_link(link)` / `sync_all()` — on-demand run of the cron's sync engine.

## Link lifecycle / UI (lift from airlock)

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

## Sync engine (shared by cron + `sync_*`)

Per link (writer role): `/item/get` (status + billed products) → `/transactions/sync` loop
(advance cursor; upsert added/modified; mark removed) → `/accounts/balance/get` (balance snapshot)
→ if `investments`: `/investments/holdings/get` (+securities, holding snapshot) and
`/investments/transactions/get` → if `liabilities`: `/liabilities/get` (liability snapshots) →
set `last_synced_at`. `ITEM_LOGIN_REQUIRED` → `status=login_required` (UI shows "repair").
**New** Plaid models + endpoints for investments (absent from `plaid_utils/models.py`).

## Deployment / k8s (`cluster/k8s/agents/plaid-mcp/`)

Two Deployments in the `plaid-mcp` namespace, each = upstream + its own `mcp-oauth-facade` sidecar:

- **plaid-mcp** (bespoke, existing `app/`): server + facade → `plaid-mcp.allegedly.works`
  (reuse `plaid-mcp-oidc`). Writer `DATABASE_URL` from the CNPG `-app` secret. ServiceAccount +
  Role (`get`/`create`/`update`/`patch` on `secrets` in-ns) to manage access-token Secrets.
- **plaid-db-mcp** (new): `crystaldba/postgres-mcp --access-mode=restricted
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

Other:

- `cronjob.yaml` (mirror `cluster/k8s/cpap-sync/cronjob.yaml`) → image's `sync` entrypoint, writer
  role.
- **Delete** `items.yaml` + the per-token `external-secret.yaml` mirrors. Provide
  `plaid-client-credentials` directly in the `plaid-mcp` ns (relocate the SOPS file).
- **airlock**: drop `plaid_chase`/`plaid_bofa` from `config.yaml`, drop `PLAID_*` env, delete its
  Plaid provider code. (airlock otherwise unchanged.)

## Migration (parallel stand-up → cutover)

1. Deploy new server + `plaid-mcp-db` (+ read-only role) alongside the running setup.
2. Backfill: for each existing token (`plaid-chase-access-token`, `plaid-bofa-access-token`) call
   `/item/get` → insert a `links` row, keep the Secret in the `plaid-mcp` ns. Run an initial full
   sync.
3. Confirm MCP clients still reach `plaid-mcp.allegedly.works` (bespoke tools), and add the new
   `plaid-db.allegedly.works` Postgres MCP.
4. Link **Interactive Brokers + Wealthfront** via `/link`.
5. Decommission airlock's Plaid providers + the ESO mirrors + `items.yaml`.

## Critical files

- `plaid_utils/`: `models.py` (+investments/liabilities Plaid models), new `link_store.py`
  (SQLAlchemy ORM + Alembic), `plaid_link.py` (link_token/exchange, from airlock), `secret_store.py`
  (k8s Secret writer), `sync.py` (engine), `mcp_server/server.py` (shrinks to 3 tools),
  `mcp_server/app.py` (FastAPI mount: MCP + `/link` + `/link/callback`), `mcp_server/web/`
  (Link UI), `BUILD.bazel` (+ `sync` binary, + frontend).
- `cluster/k8s/agents/plaid-mcp/`: new `db/` (`postgres-cluster.yaml`,
  `readonly-role-provisioner-job.yaml`, `readonly-role.sql` CM, `readonly-secret.sops.yaml`);
  `app/` adds `rbac.yaml` + `cronjob.yaml`, edits `deployment.yaml` (writer env, SA) +
  `configmap.yaml`; delete `items.yaml`, per-token `external-secret.yaml`.
- `cluster/k8s/agents/plaid-db-mcp/` (new): `deployment.yaml` (postgres-mcp + facade),
  `service.yaml`, `httproute.yaml` (`plaid-db.allegedly.works`), `configmap.yaml` (facade →
  localhost upstream), `ciliumnetworkpolicy.yaml`; OIDC app `plaid-db-mcp-oidc` via Terraform.
- `cluster/k8s/agents/airlock/`: `config.yaml`, `deployment.yaml` (drop Plaid).

## Verification

- `bbr test //plaid_utils/...` — `FakePlaidApi` gains investments/liabilities; new tests for
  `link_store` (CRUD, cursor advance), `sync` (delta apply, `removed` handling, snapshot writes,
  capability gating), and the add/exchange path.
- Read-only enforcement: a test that the `plaid_ro` role rejects writes (INSERT/UPDATE fails) while
  SELECT works.
- Sandbox: extend `plaid_utils/sandbox_smoke.py` to create a sandbox Item via the new exchange path,
  run a full sync, assert rows in every table.
- Live: deploy; open `/link`, add an institution → assert `links` row + k8s Secret created;
  `sync_all`, then SQL via the Postgres MCP (`plaid-db.allegedly.works`) returns
  holdings/transactions and `get_live_balance` works; trigger the CronJob
  (`kubectl create job --from=cronjob/plaid-mcp-sync`); use the `/link` remove button → assert
  `/item/remove` called + Secret deleted + row `revoked`.

## Out of scope

- Coinbase aggregation (unsupported by Plaid).
- Per-link distinct Plaid apps (single shared client_id/secret is correct).
