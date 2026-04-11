# Session Start Simplification

## Problem

The session start hook (`handler.py`) has grown into a monolith that:

1. **Duplicates secrets handling** that already exists in `ci_env.sh` and NixOS/home-manager SOPS integration. On CLI (NixOS), session start overwrites kubeconfig and GitHub token that h-m already provides.
2. **Has bespoke background task machinery** (apt, precommit, rootfs tune, bazel warmup) when all four follow the same pattern: "run command in background, post result to session mailbox."
3. **CI workflows duplicate setup steps** (Nix install, devtools install, secrets decryption, Bazel setup) inconsistently across 5+ workflows.

## Completed

### Secrets refactor

Replaced Python SOPS resolution with profile-configured shell env scripts.

**What was done**:
- Split `devinfra/ci_env.sh` into three independent scripts in `devinfra/secrets/`:
  - `_common.sh` — shared `try_export` helper + common secrets (BB key, OTEL token, Docker mTLS)
  - `cli_env.sh` — laptop: sources `_common.sh` only, preserves personal `GITHUB_TOKEN`/`KUBECONFIG`
  - `web_env.sh` — web agent: sources `_common.sh` + machine-user PAT + K8S_TOKEN
  - `ci_env.sh` — GHA CI: sources `_common.sh` + machine-user PAT + registry/release creds
- Each script annotated with its SOPS age recipients
- Profile `env_script` field selects which script runs (cli → `cli_env.sh`, web → `web_env.sh`)
- Daemon startup (`main.py`) runs env_script once via `source_env_script.py`:
  - Captures raw `export` lines (pasted verbatim into session env file between comment fences)
  - Parses env diff via `source script && env -0` (applied to `os.environ` for daemon-side usage)
  - Both stored and threaded through `configure()` → `server.py` → `handler.py`
- Session start reads secrets from `os.environ`, no longer calls SOPS
- `KUBECONFIG` handled separately (generated at session start, depends on proxy CA)
- Deleted: `sops_decrypt.py`, `secret_sources.py`, `SecretSource`/`SecretsConfig`, `SopsSecretSource` alias
- Extracted: `kubeconfig.py` from `secret_sources.py`
- `.envrc` → `devinfra/secrets/cli_env.sh` (no longer clobbers personal tokens)
- GHA `setup-ci-secrets` → `devinfra/secrets/ci_env.sh`
- TODO added: `os.environ.update()` footgun (env script can silently overwrite daemon vars)
- TODO added: route daemon log errors/warnings to session mailbox
- E2e test workspace has `test_env.sh` + assertion that env script output appears in session env file

### Other completed items

- `SopsSecretSource` alias squashed to `SecretSource`
- pytest-main-check separated into own pre-commit entrypoint

## Remaining

### 1. Background tasks generalization

Replace bespoke Python modules with shell commands declared in profile YAML.

| Task | What it does | Python needed? |
|------|-------------|----------------|
| apt | `apt-get update && apt-get install` | No |
| tune_rootfs | `tune2fs -m 1 /dev/vda` | No |
| bazel warmup | `bazelisk info` | No |
| precommit | `pre-commit install --install-hooks` | No |

**Model**: `background_commands` list in profile config, generic shell executor in handler,
`after: "env_file"` for ordering. Deletes `apt.py`, `tune_rootfs.py`, `bazel_warmup.py`,
`precommit.py`.

### 2. CI workflow deduplication

Create `.github/actions/setup-ci-env` composite action wrapping Nix + devtools + secrets + optional Bazel setup. Extract image digest pinning into reusable action.

**Inconsistencies to fix**: missing `setup-bazel` in `push-images.yml`/`release.yml`, inline Python setup in `ansible-lint.yml`, stale `actions/checkout@v4` in `freecad-test-image.yml`.

### 3. Future: `ci_env.sh` as full CI setup step

`ci_env.sh` is CI-exclusive — can do more than export vars:
- Registry logins (`docker login`) instead of `PROPS_REGISTRY_*`/`GHCR_*` env vars
- `GITHUB_TOKEN` in CI should be the release PAT, not the agent PAT
- Requires auditing all in-repo consumers of these env vars before rewiring

## TODOs

- Double env_script resolution on laptop (direnv + daemon startup) — minor, second run is no-op
- Container e2e test: pending verification that `test_env.sh` env script exports flow through correctly

## Non-goals

- Replacing SOPS with another secret backend
- Changing the hook daemon architecture (UDS, per-session state, FastAPI)
- Rewriting the proxy/BES interceptor
- Full UDS RPC for arbitrary mailbox messages

## Open Questions

- **apt removal timeline**: Delete now or move to `background_commands` first?
- **Kubeconfig stays in session start**: depends on `combined_ca` from proxy setup — fine, just noting the split
