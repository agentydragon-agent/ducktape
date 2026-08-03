# Haku OpenClaw spike

An isolated compatibility deployment at
<https://haku-openclaw-spike.allegedly.works> proving that OpenClaw can use
Claude Code as a persistent, subscription-backed runtime while retaining
OpenClaw sessions, workspace memory, and Haku Console's approval-gated MCP
tools.

## Trust boundary

- The OpenClaw pod contains no real Claude OAuth token, Haku Forgejo password,
  or Haku Console bearer. It receives token-shaped placeholders only. The init
  container registers the Claude placeholder in OpenClaw's per-agent auth store
  because the `claude-cli` runtime intentionally strips inherited auth variables.
- `haku-openclaw-spike-proxy` in `haku-egress-proxy` holds the real values and
  substitutes them only in `Authorization` headers for their exact hosts.
- Namespace egress permits only DNS and that proxy. The proxy has a separate
  destination allowlist enforced by Cilium.
- The pod has no Kubernetes service-account token. Privileged or external work
  remains behind the ordinary Haku Console MCP approval boundary.

## Persistent workspace

The 30 GiB PVC is mounted as `/home/openclaw`. It contains both:

- OpenClaw state and the agent workspace at
  `/home/openclaw/.openclaw/workspace`; and
- Claude Code's native transcripts/session metadata under
  `/home/openclaw/.claude`.

The deployment intentionally does **not** clone or reset a repository. The
first Haku session may reshape the workspace, initialize Git, or make it track a
new branch/remote of `haku/haku-state` using:

- `HAKU_STATE_REPO_URL` — the in-cluster Forgejo URL;
- `HAKU_GIT_USERNAME`; and
- `HAKU_GIT_PASSWORD` — a non-secret proxy placeholder.

A placeholder-only `.netrc` and Git author identity are planted so ordinary
`git clone`, fetch, and push use the mediated credential. Repository layout and
branch policy remain agent/operator decisions rather than GitOps bootstrap.

## Scope

This is a spike, not a migration of Haku Console's existing Claude chat route.
Success means:

1. Claude Code answers through OpenClaw using subscription OAuth.
2. Follow-up turns reuse one live Claude process and survive process restart by
   session resume.
3. OpenClaw local tools and Haku Console MCP tools work from Claude.
4. `MEMORY.md` and `memory/*.md` survive and are retrievable.
5. Haku can initialize and push its workspace repository without ever seeing
   the real Forgejo credential.
