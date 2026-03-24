# Cluster K8s TODO

Audit findings deferred for later.

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
