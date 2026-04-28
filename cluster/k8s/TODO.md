# Cluster K8s TODO

Audit findings deferred for later.

## Reconsider mitmproxy auto-injection in `claude-sandbox`

`cluster/k8s/kyverno/policies/inject-mitmproxy.yaml` injects
`HTTP_PROXY=http://mitmproxy.openclaw-mitmproxy:8080` (and CA bundles) into
every pod in `claude-sandbox`, `openclaw-sandbox`, `openclaw-gateway`. This
is sensible for the openclaw agent sandboxes (mitmproxy enforces egress
allowlists and provides per-agent audit), but it adds friction to
`claude-sandbox` ad-hoc Jobs that talk to in-cluster Services
(`ollama.ollama:11434` etc.) — Python `urllib`'s `NO_PROXY` matching is
hostname-based and doesn't resolve `<svc>.<ns>` against the
`10.0.0.0/8` CIDR, so requests go to mitmproxy and time out. Curl works
because it does post-DNS NO_PROXY matching.

Workarounds in use today:

- bench scripts build a `urllib.request.ProxyHandler({})` opener (see
  `cluster/docs/inference/runs/2026-04-28_initial/bench.py`).
- General-purpose Python in `claude-sandbox` would have to do the same.

Options to evaluate:

1. **Drop `claude-sandbox` from the Kyverno policy match list** — the
   sandbox is for trusted ad-hoc work, not untrusted agent egress. If
   we want audit, add it back per-Job opt-in via a label.
2. **Keep mitmproxy but extend `NO_PROXY` to include in-cluster Service
   FQDNs** (`ollama.ollama,ollama.ollama.svc,ollama.ollama.svc.cluster.local`,
   etc.). Brittle as Services proliferate.
3. **Status quo** — every script disables proxies programmatically.

Decision deferred. See <../docs/inference/runs/2026-04-28_initial/README.md>
for the incident that motivated this entry.

## OpenClaw secrets

- [ ] `agents/openclaw/sandbox-secrets/ibkr-flex-query-credentials.sops.yaml` — consider moving `query-id` out of SOPS (not sensitive)

## Missing CiliumNetworkPolicy

71% of namespaces lack network policies. Tracked in `cluster/docs/plan.md`.

**Proxy-mode services** missing the required NetworkPolicy restricting ingress
to the authentik shared proxy outpost pod (per AGENTS.md):
openclaw-mitmproxy, proxmox.

**Critical unprotected services** (no NetworkPolicy at all):
external-secrets, gitea, harbor.

## Missing resource limits

Goldilocks VPA enabled (auto mode) for nix-cache, ollama, and litellm —
will recommend limits.

- `nix-cache/app/deployment.yaml` — attic container missing `resources:`
- `ollama/app/deployment.yaml` — auth-proxy sidecar missing `resources:`
- `litellm/app/deployment.yaml` — litellm container missing `resources:`

## SecurityContext

Talos enforces `baseline` Pod Security Standards by default via PSA.
Explicit `securityContext` on Deployments is defense-in-depth. Low urgency.

Missing securityContext: litellm, ollama, devbot, grocy-sf, grocy-vallejo, proxmox-proxy,
tana-mcp, openclaw/mitmproxy, props, atuin.

## Grocy MCP startup probe

The MCP servers (grocy-mcp-sf, grocy-mcp-vallejo) crash-loop on first boot
until Grocy receives its first HTTP request (which triggers database migrations).
The MCP server tries to fetch Grocy's OpenAPI spec at startup, but Grocy returns
errors until migrations complete. After a manual visit to the Grocy web UI,
the MCP server starts successfully. Consider an init container or startup probe
that pokes Grocy's `/login` endpoint before the MCP server starts.

## Remove `kubectl-local` shell-script MCP server

Now that `cluster-kubectl-sandbox-diagnostics` (in-cluster OAuth MCP at
`kubectl-sandbox-mcp.allegedly.works`) is configured in `.mcp.json`, the local
`kubectl-local` shell-script wrapper (`devinfra/claude/kubectl-local-mcp.sh`) is
likely redundant — both resolve to the same sandbox-scoped RBAC.

Before removing:

- [ ] Verify that the in-cluster OAuth MCP server works from Claude Code **web**
      (currently blocked: claude.ai OAuth redirect mismatch prevents auth against
      the in-cluster server; plan is to configure the URL as an MCP server in
      claude.ai and have Claude Code web inherit it)
- [ ] Once web works, remove `kubectl-local` from `.mcp.json` and update CLAUDE.md
      references to `kubectl-local`

## `ghcr.io/servercontainers/samba:latest`

No semver tags published. Keep `:latest` until upstream adopts versioned releases.
