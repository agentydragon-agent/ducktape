# x/plaid

Experimental Plaid client — connect personal bank accounts, pull transactions.

Reuses `//airlock/oauth:provider` (`PlaidProvider`) for link-token creation and
public-token exchange. Adds a small client (`client.py`) for the data endpoints
PlaidProvider doesn't cover (`/sandbox/public_token/create`, `/accounts/get`,
`/transactions/sync`).

## Credentials

Stored SOPS-encrypted at `<../../secrets/plaid.sops.yaml>` — single YAML with
`client_id`, `secrets.sandbox`, `secrets.production`. Decryptable by the 5
user-level age anchors (admin + wyrm2/rugged/atlas/iguana-agentydragon).

`PlaidCreds.load()` reads it via `sops -d` and selects the secret by `$PLAID_ENV`.
Fallback: if the file is missing, it reads `PLAID_CLIENT_ID`/`PLAID_SECRET` from env.

Plaid removed the `development` environment in 2024 — only `sandbox` (fake
banks, free, unlimited) and `production` (real banks, paid; first 10 Items
free on the Trial plan for teams created on/after 2026-04-15) remain.

## Sandbox smoke test

End-to-end, no Link UI: creates a fake public_token via `/sandbox/public_token/create`,
exchanges it for an access_token, pulls `/accounts/get` and `/transactions/sync`.

```bash
PLAID_ENV=sandbox bb run //x/plaid:sandbox_smoke
```

## Real-account link

TODO. Needs a tiny localhost HTTP server hosting the Plaid Link JS widget.

## Rate limits

See <rate_limits.md>.
