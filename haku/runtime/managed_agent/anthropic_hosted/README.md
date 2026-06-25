# Managed Agents — Anthropic-hosted sandbox (design)

Status: **design / exploring.** Sibling of <../self_hosted/README.md>: same
Managed Agents loop (server-side at Anthropic), but the **sandbox runs in
Anthropic's cloud**, not our cluster. Motivation: the self-hosted worker turned
out to own a class of runtime bugs (notably the empty-tool-result deadlock,
[anthropic-sdk-go#377](https://github.com/anthropics/anthropic-sdk-go/issues/377),
plus the whole image/closure/egress bring-up). Cloud sandboxes are operated by
Anthropic and don't hit those — at the cost of moving tool execution off our
infra. This doc is how we'd keep cluster access anyway.

## The problem cloud mode creates

The cloud sandbox's `bash`/files run on Anthropic infra and **cannot reach
anything cluster-internal** — Plaid Postgres, in-cluster MCP servers, `kubectl`
via the `haku` SA, `git.allegedly.works`-internal. Everything Haku touches must
be reachable from Anthropic's side.

## Architecture: one tunnel + ephemeral in-cluster compute

Rather than expose every data-source MCP server, expose **one** thing and let
Haku spin up its own compute _inside_ the perimeter:

- **A `haku`-scoped Kubernetes MCP server, reached via an [MCP tunnel](https://platform.claude.com/docs/en/agents-and-tools/mcp-tunnels/overview).**
  Anthropic's cloud sandbox reaches a private in-cluster MCP server through the
  tunnel (no public exposure). It exposes `pods_run` / `resources_create_or_update`
  / `pods_exec` / `pods_delete`, scoped to `haku-sandbox` (the `haku` RBAC group
  already exists — `oidc-ksbx-groups:haku` → `haku-sandbox-admin` full CRUD; see
  <../../../../cluster/k8s/agents/claude-rbac/README.md>). Same MCP server we run
  as `kubectl-local` (<../../../../devinfra/claude/kubectl_local_mcp.py>).
- **Ephemeral compute pods.** Per wake, Haku `resources_create_or_update`s a pod
  in `haku-sandbox` (a trivial tools image — git/kubectl/psql/curl/cacert, **no
  `ant`, no systemd, no closure-as-PID1**) with the `haku` SA + git creds, `exec`s
  the scan into it, then `delete`s it. A pod in `haku-sandbox` has **full
  in-cluster reach** — Plaid, the in-cluster MCP servers, the
  `google-access-token` secret, internal Forgejo — so we **don't** tunnel each
  data-source MCP separately. Kyverno injects the `haku-mitmproxy` egress + RBAC +
  quota **by namespace**, so agent-created pods inherit the same fence (and PSS
  constrains what the agent can create — no privileged, runAsNonRoot).

Net: **Anthropic cloud brain + one tunneled `haku`-scoped k8s MCP + a trivial
tools image.** Arbitrary in-cluster compute still runs in `haku-sandbox` behind
the same perimeter; credentials stay in-cluster (the pod SA; vault-injected MCP
creds). No worker pod, image, or agent-runtime bugs to own.

## What to build

- **Cloud environment + agent** (`config.type` cloud, not `self_hosted`); drop the
  environment key / worker. Update `haku.agent.yaml`: MCP toolsets (the k8s MCP +
  Tana) instead of `agent_toolset_20260401` bash; manual via a **Skill** (cloud
  sandboxes auto-download skills) or a mounted GitHub repo (ducktape is on GitHub
  — no Forgejo-mirror dance).
- **Tunnel + `haku`-scoped k8s MCP server** in-cluster (register with Anthropic;
  RBAC: `pods` create/delete + `pods/exec` in `haku-sandbox`, covered by
  `haku-sandbox-admin`).
- **Tools image** (git/kubectl/psql/curl) + a fixed **pod template** the agent
  fills (don't have it hand-author pod YAML each wake).
- **Memory**: Anthropic **managed Memory** (cloud-only; not available
  self-hosted) drops the `haku-state` git apparatus — or keep `haku-state` as a
  clone in the ephemeral pod.

## Tradeoffs vs self-hosted

- **+** No agent-execution-runtime bugs (the whole `self_hosted/debug/` chain
  vanishes); Anthropic operates the hands; tighter tool surface (curated MCP, not
  broad bash+kubectl+psql).
- **−** Per-wake pod-creation latency; the cloud-vs-in-cluster filesystem split
  (do real work _inside_ the pod via `exec`, treat the cloud sandbox as
  orchestration glue); more moving parts (tunnel + MCP + RBAC), though each is
  dumber and well-trodden.
- **=** Data exposure is unchanged — tool inputs/outputs already flow to
  Anthropic's control plane even when self-hosted.

## Open design points

- `pods_run`'s image+command may be too thin for SA + secret env — likely need
  `resources_create_or_update` with a small pod manifest.
- Tunnel auth hardening: a `pods_exec`-capable MCP over a tunnel is RCE into
  `haku-sandbox` (same blast radius as today's worker, but the tunnel/RBAC is the
  fence — must be solid).
- Whether to keep `self_hosted/` as a fallback or tombstone it once this lands.
