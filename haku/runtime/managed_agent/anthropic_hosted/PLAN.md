# Build plan — Managed Agents, Anthropic-hosted sandbox

Status: **not started.** Architecture + rationale are in <README.md>; this is the
actionable build/test plan. Delete or tombstone once it's running.

Goal: run Haku on a **cloud** Managed Agents sandbox (Anthropic operates the
hands), reaching the cluster through the existing public, Authentik-authed
Kubernetes MCP — spinning **ephemeral pods** in `haku-sandbox` for in-cluster
compute. This sidesteps the self-hosted worker entirely (incl. the empty-result
deadlock, [anthropic-sdk-go#377](https://github.com/anthropics/anthropic-sdk-go/issues/377)).

## What already exists (reuse, don't build)

- **Public k8s MCP** (`containers/kubernetes-mcp-server`): `kubectl-sandbox-mcp`
  (OAuth) and `kubectl-passthrough-mcp` (bearer), both `cluster_auth_mode =
passthrough` — they act as the **caller's** token, so RBAC follows the token's
  group, and the full tool surface (`pods_run`/`pods_exec`/`resources_create_or_update`)
  is exposed (no `read_only`). → **no MCP tunnel needed.**
- **`haku` identity + RBAC**: group `haku` → `haku-sandbox-admin` (full CRUD in
  `haku-sandbox`); the `haku-k8s` machine principal
  (kubectl-sandbox-client-credentials → `groups=[haku]`) is the haku-scoped token
  path. See <../../../../cluster/k8s/agents/claude-rbac/README.md>.
- **Vault→MCP credential** mechanism: `ant beta:vaults:credentials create` with
  an `mcp_server_url` (Tana already uses `static_bearer`; see the self-hosted
  <../self_hosted/provision.sh>).
- Data-source MCP servers (google/plaid/postscanmail/manifold/tana) deployed.

## How the vault→MCP OAuth binding works

Vault MCP credentials are **keyed by `mcp_server_url`**; when the agent connects
to that URL, Anthropic injects the bearer. Two types
([docs](https://platform.claude.com/docs/en/managed-agents/vaults)):

- **`static_bearer`** — a fixed token (Tana). No refresh.
- **`mcp_oauth`** — `access_token` + `expires_at` + a `refresh` block
  (`token_endpoint`, `client_id`, `scope`, `refresh_token`, `token_endpoint_auth`
  = `none` | `client_secret_basic` | `client_secret_post`). **Anthropic refreshes
  the access token itself** (via the `refresh_token` grant); emits
  `vault_credential.refresh_failed` and offers an `mcp_oauth_validate` endpoint.

Anthropic does **not** run the interactive MCP OAuth dance (401 → discovery → DCR
→ browser) at runtime — it presents the seeded bearer, and `kubectl-sandbox-mcp`
(passthrough) just validates it via JWKS + the `groups` claim. So **any** valid
Authentik token with `audience=kubectl-sandbox-mcp` + `groups=[haku]` works.

For haku (machine, `haku`-group) two viable patterns:

1. **`static_bearer` + rotation CronJob (preferred)** — extend the existing
   `authentik-jwt-rotation` CronJob (already mints JWTs into k8s secrets on a
   schedule) to obtain a haku-group token, keep the **refresh token in a k8s
   secret**, and `ant beta:vaults:credentials update` a fresh access token into
   the vault before expiry. We own rotation; fully non-interactive; reuses
   existing infra.
2. **`mcp_oauth` seeded once** — one `authorization_code`+`offline_access` flow as
   a haku-scoped identity → store `access_token`+`refresh_token`; Anthropic
   auto-refreshes via the refresh block. No CronJob, but needs a one-time
   interactive seed and a long-lived Authentik refresh token. (The CronJob in (1)
   can also just re-seed this credential's refresh token.)

Gating Authentik detail (P0): the issued token must carry
`audience=kubectl-sandbox-mcp` **and** `groups=[haku]`.

### Secrets for the ephemeral pod (not vault env-vars)

The pod needs git creds (clone `haku-state`) and possibly the **SOPS age key**.
These are **in-cluster k8s secrets mounted into the pod** — _not_ vault
`environment_variable` credentials. Vault env-var substitution is **egress-only**:
anything that uses the secret locally (SOPS age decryption, signature
computation) sees the opaque placeholder, not the real value. So local-use
secrets stay in-cluster on the pod; vault credentials are only for the MCP bearer
(and any verbatim-in-outbound-request API keys).

## Phases (de-risk the linchpin first)

### P0 — spike: can a cloud session reach the cluster as `haku`? — **PASSED (2026-06-25)**

**Pivot during P0:** the k8s-MCP path needs a token with `aud=kubectl-sandbox-mcp`,
but the existing haku token (`secrets/haku-k8s-jwt.yaml`) has
`aud=kubectl-sandbox-client-credentials` + `groups=[haku]`. The MCP 401s it, but
**kube-apiserver accepts it directly** (200 on `haku-sandbox` pods; same audience
the Claude-web haku path uses). So v0 took **Path B: the cloud agent `curl`s
`https://kubeapi.allegedly.works` directly** with the token — no MCP, no tunnel,
no Authentik change. (MCP+second-aud stays a cleaner-tooling follow-up.)

Built by `provision.sh` (committed): cloud env (`type: cloud`, unrestricted
egress for v0), a vault `environment_variable` credential injecting the haku
token as `KUBE_TOKEN` (substituted **only** for `kubeapi.allegedly.works`), and a
bash-toolset agent. The deployment-run session ran
`curl -H "Authorization: Bearer $KUBE_TOKEN" …/haku-sandbox/pods` and listed the
pods. ✓ proves cloud egress + env-var substitution + `haku` RBAC scope.

### P1 — ephemeral compute

- Agent `resources_create_or_update`s a pod in `haku-sandbox` (a trivial tools
  image — git/kubectl/psql/curl; or reuse a toolbox image), `pods_exec`s
  `echo hi`, then `pods_delete`s it.
- **Pass =** clean create→exec→delete; output returned. Confirms write tools work
  under haku RBAC and PSS/Kyverno admit the pod.
- Decide: `pods_run` vs `resources_create_or_update` (SA + secret env likely needs
  the full manifest); settle the **pod template**.

### P2 — full scan

- The pod clones `haku-state` (git creds via mounted secret), scans **one** source
  (e.g. the Gmail token + a simple query), writes a finding, commits + pushes
  `haku-state`, exits.
- Author the **cloud run procedure** (haku/base + run.md variant, or a Skill):
  "create pod → exec scan → commit haku-state → delete." Mind the cloud-sandbox vs
  in-pod **filesystem split** — do real work in the pod via `exec`.
- Decide **memory**: managed Memory (cloud-only) vs git `haku-state` in-pod.
- **Pass =** a wake produces a real `haku-state` commit, no manual steps.

### P3 — schedule + soak

- Scheduled deployment (cloud wake trigger). Run for a few days; compare cost,
  latency, reliability against `self_hosted`. Then decide whether to tombstone
  `self_hosted/`.

## Artifacts to land (mostly P2/P3)

- `anthropic_hosted/haku.environment.yaml` (cloud), `haku.agent.yaml`
  (mcp_servers = [k8s, tana]; system prompt → manual), `haku.deployment.yaml`
  (schedule), `provision.sh` (create env/vault/agent/deployment via `ant`).
- A tools image (or reuse) + the pod template.
- Cloud run procedure (haku/base + run.md edits, or a Skill).

## Open unknowns / risks

- **Authentik claims (the real P0 gate)**: does an existing/new provider mint a
  haku token carrying both `audience=kubectl-sandbox-mcp` and `groups=[haku]`, and
  can a cloud session reach `*.allegedly.works`? (Credential schema + rotation are
  resolved above — `static_bearer` + the `authentik-jwt-rotation` CronJob.)
- Per-wake pod-creation latency (acceptable for a background scanner; measure P3).
- `pods_exec` over a public MCP = RCE into `haku-sandbox` — same blast radius as
  today's worker, but the Authentik/RBAC scoping is the fence; keep it tight.

## Workflow

Worktree + PR per phase. P0 is mostly `ant beta:*` calls + one vault credential +
a throwaway agent — cheap, and it gates the rest.
