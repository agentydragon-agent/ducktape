# Session: DinD + CI SOPS Key Migration

Session date: 2026-04-09

## What Was Done

### 1. Docker-in-Docker Daemon (complete, running)

Persistent DinD with mTLS on Proxmox for CI container tests.

**Commits:**

- `8ee2d8ee5` — DinD deployment, mTLS certs, SOPS secrets
- `dcc23aec1` — fix openebs dependency name
- `f8b1c8c19` — add Unix socket for readiness probe
- `6bb191c1e` / `d0aee3478` — py_test macro env_inherit, plan update
- `137a62bf9` — Hetzner firewall port 2376

**Key files:**

- `cluster/k8s/docker-ci/` — all k8s manifests (deployment, TLSRoute, service, PVC, certs)
- `secrets/docker-ci/` — CA key, client key, server key (SOPS)
- `util/testing/docker_mtls.py` — pytest fixture (autouse, assembles cert dir from env + runfiles)
- `devinfra/python/defs.bzl` — `requires_docker=True` auto-injects env_inherit + fixture
- `devinfra/bb_remote.sh` — forwards `DOCKER_CLIENT_KEY` via `--remote_run_header`
- `cluster/k8s/gateway/gateway.yaml` — `docker-ci-tls` listener on port 2376

**Verified:** mTLS works end-to-end via `curl https://docker-ci.allegedly.works:2376/v1.47/version`

### 2. CI SOPS Age Key (complete, deployed)

Replaced 4 individually-synced GHA secrets + 3 BB org secrets with a single `SOPS_AGE_KEY`.

**CI key:** `age1zl5lv4g0lzd4pcwx9q4vvq0w4rpmkde5r68k4n2zu89urmnx9svs3c2mef`
Private key in BB org secrets and GHA (via tofu-controller sync).

**Commits:**

- `a0183bc33` — CI age key, `ci_env.sh`, `.sops.yaml` rules, github-secrets-sync TF
- `7d68c2edc` — GHA workflows → `setup-ci-secrets` action
- `5dfb199f9` — fix data source `removed` blocks
- `e5b8a80c2` — GHCR + GH release PAT to SOPS
- `f12977a7b` — TODO for BB workflow migration
- `194a11dea` — Harbor adopt SOPS-managed creds

**Key files:**

- `devinfra/ci_env.sh` — decrypts all CI secrets, used by direnv/hook/GHA
- `.sops.yaml` — `&ci` key with narrow access
- `.github/actions/setup-ci-secrets/action.yml` — installs sops, runs ci_env.sh
- `cluster/terraform/gitops/github-secrets-sync/main.tf` — syncs `SOPS_AGE_KEY` to GHA
- `secrets/ci/` — attic token, harbor creds, GHCR creds, GH release PAT

**Secrets in SOPS (all decryptable by `&ci`):**

| Env var                 | SOPS file                                    |
| ----------------------- | -------------------------------------------- |
| `BUILDBUDDY_API_KEY`    | `secrets/buildbuddy.yaml`                    |
| `GITHUB_TOKEN`          | `secrets/github-pat-agentydragon-agent.yaml` |
| `DOCKER_CLIENT_KEY`     | `secrets/docker-ci/client-key.sops.pem`      |
| `ATTIC_TOKEN`           | `secrets/ci/attic-token.sops.yaml`           |
| `PROPS_REGISTRY_*`      | `secrets/ci/harbor-ci-robot.sops.yaml`       |
| `GHCR_TOKEN`/`USERNAME` | `secrets/ci/ghcr-credentials.sops.yaml`      |
| `GH_RELEASE_PAT`        | `secrets/ci/gh-release-pat.sops.yaml`        |

### 3. Session start hook integration

`handler.py` runs `ci_env.sh` at session start, bakes static exports into env file.
No per-Bash-command decryption — one-time at hook time.

## Completed (this session continued)

- **CI consolidated to GHA-only** — `buildbuddy.yaml` deleted, all CI via GHA → `bb-remote`
- **Per-artifact `github_release` macro** — replaces monolithic `bb_release_bin`
- **bb-remote uses RBE worker image** — fixes pycairo/system dep issues
- **Docker CI pruning CronJobs** — hourly container prune, weekly image prune
- **Harbor creds adopted** from SOPS via TF module
- **CI green**: 13/13 push-images, 6/6 releases

## Remaining

1. **Remove old BB org secrets** — GHCR_TOKEN, GHCR_USERNAME, GH_RELEASE_PAT
   (SOPS_AGE_KEY is the only one needed now)
2. **Drop bazelisk wrapper for bb CLI** — `bb` embeds bazelisk + reads API key natively
3. **Delete dead code** — `generate_buildbuddy.py`, `test_generate_buildbuddy.py`
   (sync_pins still uses ARTIFACTS from artifacts.py, keep that)
4. **Extend bbapi CLI** — chunked log fetching for BB workflow debugging

### Design decisions made

- **mTLS over TLSRoute** (not HTTPRoute) — Docker daemon verifies client certs directly
- **`--remote_run_header`** for BB secrets (not `--env`) — not cached, not visible in UI
- **`ci_env.sh` runs once at session start** (not on every Bash call) — baked into env file
- **Separate `&ci` and `&claude-web` keys** — independent recipients, different scopes
- **Harbor `secret` field** — provider supports setting robot password to specific value

## Next: Consolidate CI to GHA-only

Plan approved at `~/.claude/plans/frolicking-cooking-stearns.md`.

Delete `buildbuddy.yaml` entirely. Replace with 3 GHA workflows calling
`bb-remote`:

1. `bazel-ci.yml` — test + build
2. `release.yml` — wheel build + GitHub releases
3. `push-images.yml` — matrix job for 13 push targets

`bb` and `bb-remote` come from Nix devshell (`nix profile install .#devtools`).

**Uncommitted files to handle**: `generate_buildbuddy.py` and `buildbuddy.yaml`
have partial SOPS changes that should be reverted/deleted as part of this work.

## Context for Successor

- Plan file: `~/.claude/plans/frolicking-cooking-stearns.md`
- Memory: `~/.claude/projects/-home-agentydragon-code-ducktape/memory/project_ci_sops_key.md`
- DinD README: `cluster/k8s/docker-ci/README.md`
- Skip `ducktape-git-hook` in pre-commit (broken Nix package, `validate_flux_build` import error)
- BB CLI source: `/code/github.com/buildbuddy-io/buildbuddy/cli/`
- Harbor provider source: `/code/github.com/goharbor/terraform-provider-harbor/`
- CI age key public: `age1zl5lv4g0lzd4pcwx9q4vvq0w4rpmkde5r68k4n2zu89urmnx9svs3c2mef`
