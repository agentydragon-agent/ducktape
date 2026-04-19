# MCP + OAuth + Authentik: What We Learned

Notes from building an in-cluster MCP server (`kubectl-sandbox-mcp`) that
authenticates MCP clients via Authentik and scopes any caller to
sandbox-level Kubernetes permissions via token exchange.

## Goal

Let anyone (including a cluster admin) connect to an MCP server from
Claude.ai / Claude Code, authenticate via Authentik consent screen, and
get Kubernetes access **scoped to the `kubectl-sandbox-users` group** —
no privilege escalation, even if the authenticating user has cluster-admin
elsewhere.

## The MCP Auth Flow (as the MCP spec defines it)

```text
MCP client (Claude Code)
  │ 1. Connect to MCP server (HTTP or SSE transport)
  │ 2. Server responds 401 with WWW-Authenticate: Bearer
  │ 3. Client fetches /.well-known/oauth-protected-resource on MCP server
  │    → gets authorization_servers (URL of the OAuth server)
  │ 4. Client fetches /.well-known/oauth-authorization-server on that URL
  │    → gets authorize/token/registration endpoints
  │ 5. Client performs DCR: POSTs to registration_endpoint
  │    → server issues a fresh client_id/secret for this MCP client
  │ 6. Client does OAuth authorization_code flow (browser consent)
  │ 7. Client exchanges code for access token
  │ 8. Client reconnects with Authorization: Bearer <token>
  ▼
MCP server validates token, handles tool calls
```

**Step 5 (DCR) is the killer** — MCP assumes the OAuth server implements
[RFC 7591 Dynamic Client Registration](https://www.rfc-editor.org/rfc/rfc7591).
Each MCP client dynamically registers itself rather than being pre-provisioned.

## Authentik's DCR status

**Authentik does NOT support DCR as of 2026-04.** See upstream issue
[goauthentik/authentik#8751](https://github.com/goauthentik/authentik/issues/8751)
— feature request open since February 2024, milestone "Release 2026.8.0:
Required", not yet shipped.

Authentik's `/.well-known/openid-configuration` does **not** advertise a
`registration_endpoint`, which is why Claude Code errors:

```text
SDK auth failed: Incompatible auth server: does not support dynamic client registration
```

## kubernetes-mcp-server (containers/kubernetes-mcp-server)

Go binary, single OIDC config. Two relevant features:

- `require_oauth = true` — validate incoming Bearer tokens via JWKS
- `cluster_auth_mode = passthrough` — forward the caller's JWT to kube-apiserver
- `cluster_auth_mode = kubeconfig` — use the pod's own kubeconfig (fixed SA)
- `token_exchange_strategy = rfc8693` — RFC 8693 token exchange for
  swapping caller's token for a scoped one before forwarding

**Well-known proxy behavior**: the server proxies `/.well-known/*` requests
to the upstream OAuth server (Authentik) and returns the response to the MCP
client. If Authentik doesn't implement an endpoint, we get whatever
Authentik returns (404 HTML).

### v0.0.60 bug we hit

When Claude Code requests `/.well-known/oauth-authorization-server`:

- Server proxies to Authentik
- Authentik returns 404 HTML (only `openid-configuration` exists)
- v0.0.60 tries to JSON-decode the HTML → 500
- Claude Code can't even reach the DCR error

**Fix on upstream main** (unreleased as of 2026-04): 404 fallback that
generates `oauth-authorization-server` from `openid-configuration`.
We built our own image pinned at upstream commit
`8d2bb9b748ba77075a0305389c105f202d7e9751` — see
`third_party/kubernetes-mcp-server-pin.txt` and the CI workflow job.

### DCR support

The Go server doesn't implement DCR itself — it just proxies whatever
the upstream auth server provides. If Authentik doesn't expose
`registration_endpoint`, neither does our MCP server. No config flag
makes the Go server synthesize DCR.

## The three ways to solve DCR-with-Authentik

### Option A: Pre-registered client (what we can do today)

Claude Code supports pre-configured OAuth clients via:

```bash
claude mcp add --transport http kubectl-sandbox \
  https://kubectl-sandbox-mcp.allegedly.works/mcp \
  --client-id kubectl-sandbox-mcp \
  --client-secret \
  --callback-port 8080
```

Requires:

- Authentik OAuth2 provider's `client_id` (TF-defined)
- Authentik OAuth2 provider's `client_secret` (TF-generated, in Vault/SOPS)
- A registered redirect URI of `http://localhost:8080/callback` on that
  Authentik provider

Downside: each user needs to get the client secret out-of-band. It's a
shared secret across all users of this MCP server, so rotation requires
coordination.

Claude Code also supports **CIMD** (Client ID Metadata Document) — a static
document that describes a pre-registered client. This would allow us to
skip the `--client-secret` flag for public clients. Authentik doesn't
currently advertise CIMD either.

### Option B: FastMCP `OIDCProxy` in front

Our internal `mcp_infra/authentik_auth/auth.py` uses FastMCP's `OIDCProxy`.
**FastMCP implements DCR in the MCP server itself**: when an MCP client
POSTs to `/register`, FastMCP issues a synthetic client_id/secret and
stores the registration locally. When that synthetic client does OAuth,
FastMCP proxies the flow to Authentik using one pre-registered
confidential client (the one we provision in TF).

This is how grocy-mcp-sf, grocy-mcp-vallejo, airlock, and authentik-mcp-poc
all work. They're Python FastMCP servers using `build_authentik_auth()`.

To apply this to kubectl-mcp: wrap the Go `kubernetes-mcp-server` behind
a Python FastMCP proxy that handles OAuth and forwards tool calls. Either:

- Run kubernetes-mcp-server as a sidecar (stdio or HTTP) and `FastMCPProxy`
  to it
- Reimplement kubectl tools natively in Python (significant rewrite)

### Option C: Wait for Authentik DCR

Scheduled for Authentik 2026.8.0. Once it ships:

- Enable DCR on the provider (or tenant, depending on how Authentik
  implements it)
- kubernetes-mcp-server will proxy the `registration_endpoint` through
  to Authentik
- MCP clients register dynamically as designed

Unknown timeline. Low cost to wait if we use Option A in the meantime.

## Supporting design decisions (also learned the hard way)

### Cluster networking / hairpin

- `api.allegedly.works` / `auth.allegedly.works` resolve to the VPS IPs
  (5.78.x.x) of the nodes running Cilium Gateway with `hostNetwork`.
- Pods sending traffic to those IPs _hairpin_ through the Gateway.
- **Hairpin routing works** in our Cilium setup — but CiliumNetworkPolicy
  evaluates at the final pod-to-pod hop, not just at ingress.
- Authentik's CNP only allowed ingress from specific namespaces. Pods in
  `kubectl-sandbox-mcp` / `kubectl-passthrough-mcp` were rejected at the
  final hop even though the Gateway routed them.
- **Fix**: add MCP namespaces to `authentik-server-ingress` CNP's
  `fromEndpoints`.

### TLS passthrough for client cert auth

Related lesson from earlier: `api.allegedly.works` uses TLS passthrough
(TLSRoute on Cilium Gateway, not HTTPRoute). This preserves client certs
to the API server. For MCP servers we use HTTPRoute (TLS termination) —
because MCP uses Bearer tokens in HTTP headers, not client certs.

### ConfigMap + Secret drop-ins for kubernetes-mcp-server

The server takes a single `--config` file. To avoid mixing URLs with
secrets in one Secret:

- ConfigMap with `00-public.toml` (URLs, audiences, etc.)
- Secret with `01-secret.toml` (client_secret, sts_audience when
  TF-generated)
- Use both `--config=00-public.toml` and `--config-dir=<conf.d>` — the
  server loads drop-ins in lexical order, later files override.

### kube-apiserver AuthenticationConfiguration

kube-apiserver only validates JWTs from issuers listed in the
`AuthenticationConfiguration`. Each Authentik provider needs an entry
with its issuer URL + audience. Entries in
`cluster/terraform/main/infrastructure.tf`.

Changing the audience/issuer requires updating this config, which Talos
picks up via the mounted file (no reboot needed — kube-apiserver watches
the file).

### OIDC group claim mapping

Authentik's per-provider claim mapping has a prefix:
`username = oidc-ksbx:`, `groups = oidc-ksbx-groups:`. So a user in
Authentik group `kubectl-sandbox-users` appears to kube-apiserver as
group `oidc-ksbx-groups:kubectl-sandbox-users`. RoleBindings target
that prefixed group name.

## Current state (2026-04-19)

Three kubectl MCP servers:

| Name                      | Transport             | Auth                                      | Permissions                                            |
| ------------------------- | --------------------- | ----------------------------------------- | ------------------------------------------------------ |
| `kubectl-local`           | stdio (local process) | client cert in kubeconfig                 | `kubectl-sandbox-users` group (via cert `O=` field)    |
| `kubectl-passthrough-mcp` | HTTP                  | OAuth passthrough — forwards caller's JWT | caller's own OIDC group permissions                    |
| `kubectl-sandbox-mcp`     | HTTP                  | OAuth + RFC 8693 token exchange           | scoped to `kubectl-sandbox-users` regardless of caller |

**All three work as of the well-known fix** — needed:

- Custom image build from upstream main (well-known 404 fallback)
- Authentik CNP allows MCP namespaces to reach it
- AuthenticationConfiguration entries for both issuers
- TLSRoute at `api.allegedly.works` for client cert passthrough

**What doesn't work yet from Claude Code without workaround**:

- DCR-based OAuth add. Use pre-registered client:
  ```bash
  claude mcp add --transport http kubectl-sandbox \
    https://kubectl-sandbox-mcp.allegedly.works/mcp \
    --client-id kubectl-sandbox-mcp --client-secret --callback-port 8080
  ```
  Needs the Authentik provider's client_secret; also needs
  `http://localhost:8080/callback` added to the provider's allowed
  redirect URIs.

## Followups

- [ ] Add `http://localhost:*/callback` (or specific ports) to Authentik
      OAuth2 providers' allowed redirect URIs so `claude mcp add --client-id`
      works out of the box
- [ ] Document how to get the client_secret from Vault/SOPS
- [ ] Evaluate wrapping kubernetes-mcp-server with FastMCP `OIDCProxy` to
      get DCR "for free" via the existing pattern
- [ ] Watch for Authentik DCR release (2026.8.0?); once shipped, switch
      back to upstream kubernetes-mcp-server image
- [ ] Consider Gatus endpoints and dashboards for MCP server health
