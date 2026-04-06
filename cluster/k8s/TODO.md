# Cluster K8s TODO

Audit findings deferred for later.

## OpenClaw secrets: populate placeholders

These SOPS secrets contain `REPLACE_ME` and must be populated with real credentials
before unsuspending the `openclaw-gateway-secrets` / `openclaw-sandbox-secrets`
kustomizations. Edit with `sops <file>`, commit, push.

- [ ] `agents/openclaw/sandbox-secrets/coinbase-api-credentials.sops.yaml` — Coinbase portal (`api_key`, `api_secret`)
- [ ] `agents/openclaw/sandbox-secrets/ibkr-flex-query-credentials.sops.yaml` — consider moving `query-id` out of SOPS (not sensitive)

## Missing CiliumNetworkPolicy

71% of namespaces lack network policies. Tracked in `cluster/docs/plan.md`.

**Proxy-mode services** missing the required NetworkPolicy restricting ingress
to the authentik shared proxy outpost pod (per AGENTS.md):
openclaw-mitmproxy, proxmox.

**Critical unprotected services** (no NetworkPolicy at all):
vault, external-secrets, gitea, harbor.

## Missing resource limits

Goldilocks VPA enabled (auto mode) for nix-cache, ollama, and litellm —
will recommend limits.

- `nix-cache/app/deployment.yaml` — attic container missing `resources:`
- `ollama/app/deployment.yaml` — auth-proxy sidecar missing `resources:`
- `litellm/app/deployment.yaml` — litellm container missing `resources:`

## SecurityContext

Talos enforces `baseline` Pod Security Standards by default via PSA.
Explicit `securityContext` on Deployments is defense-in-depth. Low urgency.

Missing securityContext: litellm, ollama, devbot, grocy, proxmox-proxy,
tana-mcp, openclaw/mitmproxy, props, atuin.

## `ghcr.io/servercontainers/samba:latest`

No semver tags published. Keep `:latest` until upstream adopts versioned releases.
