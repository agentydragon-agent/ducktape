# Cluster K8s TODO

Audit findings deferred for later.

## Missing CiliumNetworkPolicy

71% of namespaces lack network policies. Tracked in `cluster/docs/plan.md`.

**Proxy-mode services** (behind authentik shared proxy outpost) that MUST have
NetworkPolicy restricting ingress to the outpost pod (per AGENTS.md):
alloy-otlp, goldilocks, google-workspace-mcp, grocy, hubble-ui, loki,
longhorn, openclaw, openclaw-mitmproxy, proxmox, scanner-filebrowser.

**Critical unprotected services**: vault, external-secrets, gitea, harbor.

## Missing resource limits

Goldilocks VPA enabled (auto mode) for nix-cache and ollama — will recommend limits.
litellm now has goldilocks enabled (this commit).

- `nix-cache/app/deployment.yaml` — attic container missing `resources:`
- `ollama/app/deployment.yaml` — auth-proxy sidecar missing `resources:`
- `litellm/app/deployment.yaml` — litellm container missing `resources:`

## SecurityContext

Talos enforces `baseline` Pod Security Standards by default via PSA.
Explicit `securityContext` on Deployments is defense-in-depth. Low urgency.

Missing securityContext: litellm, ollama, scanner (samba), devbot, grocy,
proxmox-proxy, tana-mcp, openclaw/mitmproxy, props, activitywatch, atuin.

## Inconsistent namespace placement

14+ standalone directories inline `namespace.yaml` instead of using the
`namespace/` subdirectory pattern. Not worth fixing unless the service
gains siblings that need grouping.

## `ghcr.io/servercontainers/samba:latest`

No semver tags published. Keep `:latest` until upstream adopts versioned releases.
