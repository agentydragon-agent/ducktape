# Tana MCP Facade

Public OAuth-facing facade for the in-cluster `tana-mcp` deployment.

## Purpose

Tana Desktop only exposes a local bearer-authenticated MCP server. This facade
adds:

- Authentik-backed MCP OAuth/DCR for remote clients
- server-held bearer injection on the downstream hop to internal `tana-mcp`

The Tana personal access token stays in Kubernetes and is never returned to the
caller.

## Boundaries

- Upstream: callers authenticate to this service via Authentik
- Downstream: the facade talks to internal `tana-mcp` with a static bearer token
- Authorization: Authentik application policy is the source of truth for who
  may use the facade

Primary access control is intended to live in Authentik/Terraform via the
dedicated group `tana-agentydragon-gmail-com-account-access`, which grants
access to the OAuth application for the `agentydragon@gmail.com` Tana account.

## Config

Environment prefix: `TANA_MCP_FACADE_`

- `AUTH__OIDC_ISSUER`
- `AUTH__OIDC_CLIENT_ID`
- `AUTH__OIDC_CLIENT_SECRET`
- `AUTH__PUBLIC_BASE_URL`
- `DOWNSTREAM_URL`
- `STATIC_BEARER_TOKEN`

The facade serves:

- `/mcp` for MCP traffic
- `/healthz` for pod health
