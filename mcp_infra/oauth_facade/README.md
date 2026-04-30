# mcp-oauth-facade

Generic Authentik-backed OAuth facade for upstream MCP servers. Fronts an
internal MCP server with `OIDCProxy` + `JWTVerifier` so claude.ai (or any
MCP-OAuth client) can authenticate against Authentik before reaching the
upstream.

## Upstreams

- **HTTP** (`HttpUpstream`): a Streamable HTTP MCP endpoint reachable inside
  the cluster. Optional server-held bearer token forwarded to the upstream
  on every hop.
- **Stdio** (`StdioUpstream`): a subprocess that speaks MCP over stdin/stdout.
  The subprocess inherits the facade pod's environment, so Secret-mounted env
  vars (e.g. `MANIFOLD_API_KEY`) reach the child unchanged.

## Configuration

All env-driven via `pydantic-settings`:

```
MCP_FACADE_AUTH__OIDC_ISSUER=https://auth.allegedly.works/application/o/<slug>/
MCP_FACADE_AUTH__OIDC_CLIENT_ID=<client_id>
MCP_FACADE_AUTH__OIDC_CLIENT_SECRET=<secret>
MCP_FACADE_AUTH__PUBLIC_BASE_URL=https://<host>
MCP_FACADE_FACADE_NAME=<human readable name>
MCP_FACADE_UPSTREAM__KIND=http        # or stdio
MCP_FACADE_UPSTREAM__URL=...          # http only
MCP_FACADE_UPSTREAM__BEARER_TOKEN=... # http only, optional
MCP_FACADE_UPSTREAM__COMMAND=["..."]  # stdio only (JSON list)
```

The image binary is at `//x/mcp_oauth_facade:image` (`ghcr.io/agentydragon/mcp-oauth-facade`).
