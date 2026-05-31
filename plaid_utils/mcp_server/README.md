# plaid_utils/mcp_server

Plaid v0 runtime package.

The deployed image now runs [`app.py`](app.py): a FastAPI web UI for Plaid Link
management plus a shared synchronous full-refresh sync engine. The agent-facing
read path is not this package; it is `crystaldba/postgres-mcp` pointed at the
synced Postgres database with a read-only role.

## Entrypoints

- `//plaid_utils/mcp_server:app_cli` / `server_image`: web UI on `:8080`.
- `//plaid_utils/mcp_server:sync_cli` / `sync_image`: CronJob entrypoint that
  refreshes every active link into Postgres.
- `//plaid_utils/mcp_server:server_cli`: legacy static-item Plaid MCP server kept
  for tests and comparison; it is not the v0 deployment.

## Configuration

The web and sync entrypoints use `PlaidWebSettings`:

- `PLAID_MCP_PLAID_ENV` — `sandbox` or `production`.
- `PLAID_MCP_CLIENT_ID` / `PLAID_MCP_CLIENT_SECRET` — Plaid app credentials.
- `DATABASE_URL` — writer Postgres URL, usually CNPG secret `plaid-mcp-db-app`.
- `PLAID_MCP_PUBLIC_BASE_URL` — public UI origin; defaults to
  `https://plaid-mcp.allegedly.works`.
- `PLAID_MCP_TRANSACTION_DAYS` / `PLAID_MCP_INVESTMENT_TRANSACTION_DAYS` — v0
  full-refresh windows.

Access tokens are one Kubernetes Secret per Plaid Item and are never stored in
Postgres. The web UI writes those Secrets; the sync job reads them.

## Deployment

GitOps manifests live under
[`cluster/k8s/agents/plaid-mcp/`](../../cluster/k8s/agents/plaid-mcp/README.md).
The human UI is `https://plaid-mcp.allegedly.works/link`; the read-only SQL MCP
is `https://plaid-db.allegedly.works/mcp`.
