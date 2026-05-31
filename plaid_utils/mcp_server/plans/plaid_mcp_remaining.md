# Plaid MCP Remaining Plan

_Updated 2026-05-31._

## Current State

v0 now has the Plaid Link management UI at `https://plaid-mcp.allegedly.works/` and `/link`, product-profile selection, access-token Secrets, CNPG Postgres, Plaid-shaped synced tables, append-only API/sync audit tables, the 12-hour full-refresh CronJob, and the read-only SQL MCP surface at `plaid-db.allegedly.works`.

The agent-facing read path is intentionally Postgres SQL only. There are no v0 bespoke Plaid MCP tools.

## Cutover From Airlock

Airlock still owns the old Plaid wiring until the v0 UI and sync path are proven with the existing Items and at least one new link.

Remaining cutover work:

1. Keep using the same Plaid `client_id` and `client_secret`; make the `plaid-mcp` namespace the durable source of those credentials.
2. Confirm the existing Chase and Bank of America access-token Secrets are present in `plaid-mcp` and synced through the new database path.
3. Remove Airlock Plaid providers after confidence:
   - Delete `plaid_chase` and `plaid_bofa` from `cluster/k8s/agents/airlock/config.yaml`.
   - Drop Airlock Plaid env and token ESO wiring.
   - Remove `cluster/k8s/agents/plaid-mcp/app/external-secret.yaml` token mirrors if no longer needed.
4. Retire the old static-item MCP path in `plaid_utils/mcp_server/server.py` once no tests or docs depend on it as the active shape.

## New Link Validation

Use `https://plaid-mcp.allegedly.works/` or `/link` to add investment-capable institutions.

Priority links:

- Interactive Brokers: use an investment profile first.
- Wealthfront: use an investment profile first.

For each new Item:

1. Link through the UI.
2. Confirm a Kubernetes access-token Secret and `links` row are created.
3. Run or wait for sync.
4. Verify SQL rows for accounts, holdings, securities, investment transactions where available, balances, and `plaid_api_events`.
5. Verify the UI scope-upgrade, sync, remove, and repair paths before unwiring Airlock.

## v0 Hardening

- Add or run the sandbox smoke through the new exchange path: create a sandbox Item, sync it, and assert rows in every expected table.
- Keep tests focused on product-profile gating, full-refresh reconciliation, absent-in-window transaction removal, pending-to-posted replacement, investment transaction pagination, holding/liability snapshots, API event redaction, `sync_runs`, and same-Item sync locking.
- Keep Postgres comments useful for MCP discovery whenever schema changes.

## v1 Sync

Implement Plaid-recommended incremental behavior after v0 is stable.

Primary docs:

- <https://plaid.com/docs/transactions/sync-migration/>
- <https://plaid.com/docs/transactions/transactions-data/>
- <https://plaid.com/docs/transactions/webhooks/>
- <https://plaid.com/docs/api/products/investments/>
- <https://plaid.com/docs/api/products/liabilities/>
- <https://plaid.com/docs/api/accounts/>
- <https://plaid.com/docs/api/webhooks/webhook-verification/>

Transactions:

- Use `/transactions/sync`, not `/transactions/get`, for recurring updates.
- Keep one cursor per Item unless we deliberately introduce per-account cursors.
- Accumulate all pages before applying a delta; commit `next_cursor` only after data changes commit.
- On `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`, discard the partial batch and restart from the cursor used for that loop.
- Treat pending transactions as provisional and posted transactions as mutable.

Webhooks:

- Configure the Plaid webhook URL in `/link/token/create`.
- Verify Plaid webhook JWTs through `/webhook_verification_key/get`.
- Use webhooks to enqueue sync; keep Cron as the missed-webhook backstop.

Investments and liabilities:

- Holdings are current-state snapshots from `/investments/holdings/get`.
- Investment transactions use date windows and `count`/`offset` pagination; refetch an overlapping recent window for recurring sync.
- Liabilities are current-state snapshots from `/liabilities/get`.

## Optional Bespoke MCP Tools

Only add non-DB operations if the SQL read path proves insufficient:

- `get_live_balance(link, account=None)` using `/accounts/balance/get`.
- `sync_link(link)` and `sync_all()` for manual sync triggers.

Do not add link add/remove/repair tools; those stay in the human `/link` UI.
