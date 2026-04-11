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

### Background tasks generalization

Replaced bespoke Python modules with `background_commands` list in profile YAML config.

**What was done**:

- Added `BackgroundCommand` model to `config.py` with `name`, `command`, `timeout`, `after_env` fields
- Added `background_commands: list[BackgroundCommand]` to `ProfileConfig`, replacing
  `install_apt_packages: bool` and `bazel_warmup: str | None`
- Generic `_run_background_command()` executor in `handler.py`:
  - Posts lifecycle messages: "Task [...] started." / "completed successfully." / "failed, see hook daemon logs for details."
  - Passes `HOOK_DAEMON_SOCK` env var so scripts can post additional messages via
    `curl --unix-socket $HOOK_DAEMON_SOCK -X POST http://localhost/mailbox -d '{"message":"..."}'`
  - Immediate commands (`after_env=False`) launch in parallel with proxy/container setup
  - Deferred commands (`after_env=True`) source the session env file and launch after it's written
- Added `POST /mailbox` endpoint to `server.py` for background commands to send messages
- Moved tasks into config YAML: CLI profile gets `bazel info` (after_env), web profile gets
  apt install, rootfs tuning, pre-commit setup, bazel info (after_env)
- Deleted: `apt.py`, `tune_rootfs.py`, `bazel_warmup.py`, `precommit.py`, `test_bazel_warmup.py`
- Updated `session_context.mako` template: replaced `precommit_installing` section with
  generic "Background tasks" listing all configured commands

### Shim refactor (landed separately)

Replaced `wrappers/` directory (bazel.py, git.py, install.py) with thin shims and
server-side logic:

- New `ShimExecRequest` / `ShimBlocked` / `ShimExecve` models in `models.py`
- `POST /shim-exec` endpoint in server handles all shim logic (git safety checks,
  bazelisk `--bazelrc` injection, proxy credential refresh, JWT expiry warnings)
- `report_shim()` in `client.py` — thin client used by shim scripts
- Shim scripts (`bazelisk.py`, `git.py`) are now ~5 lines: call `report_shim()`, exec result
- `update_proxy_creds()` and `/wrapper-exec` endpoint removed (replaced by `/shim-exec`)
- `create_app()` now takes `profile` parameter for server-side shim logic

### CI workflow deduplication

Consolidated 7 GHA setup actions into 3 via `setup-ci-env` composite action wrapping
Nix + devtools + secrets + Bazel setup. Deleted `setup-buildbuddy`, `bazel-repo-cache`,
`setup-python-env`, `setup-nix-direnv`. Updated all workflows to use the new action.

### Profile config consolidation

Eliminated `HookConfig` wrapper — each profile is now a standalone YAML file.

**What was done**:

- Moved `otel`, `k8s`, `pre_commit` from top-level `HookConfig` into `ProfileConfig`
- Added `context_template` field to `ProfileConfig` for per-profile session context templates
- Added `ProfileConfig.load(config_path)` classmethod
- Split `.claude_hooks/config.yaml` into `.claude_hooks/cli.yaml` and `.claude_hooks/web.yaml`
- `DUCKTAPE_CLAUDE_HOOKS_PROFILE` env var selects the profile file path (set in `.envrc`
  for CLI, `web_setup.sh` for web)
- Daemon startup loads one profile directly — no `resolve_profile()`, no `is_web_mode()`,
  no `default_profiles` map
- `post_tool_use.evaluate()` receives `pre_commit` as parameter instead of re-loading
  config from disk on every PostToolUse call
- `_render_extra_context()` loads template from `profile.context_template` instead of
  hardcoded `.claude_hooks/templates/context.mako` path
- Deleted: `HookConfig`, `DefaultProfiles`, `is_web_mode()`

## Remaining

### Future: `ci_env.sh` as full CI setup step

`ci_env.sh` is CI-exclusive — can do more than export vars:

- Registry logins (`docker login`) instead of `PROPS_REGISTRY_*`/`GHCR_*` env vars
- `GITHUB_TOKEN` in CI should be the release PAT, not the agent PAT
- Requires auditing all in-repo consumers of these env vars before rewiring

### Statusline packaging separation

The statusline hook is installed system-wide (home-manager) so it works in non-ducktape
sessions, but this causes two `claude-hooks` installations on dev machines (home-manager +
devShell/envrc). Cleaner fix: extract statusline into its own package, which requires
separating client/server/protocol definitions so the statusline package doesn't drag in
the full daemon dependency tree. Low priority — the dual install works, just wastes a
Nix closure.

### Per-profile session context

`context_template` field is wired up (profile consolidation). Remaining work:

- Split `.claude_hooks/templates/context.mako` into `cli_context.mako` and `web_context.mako`
- Move secrets/kubeconfig sections from shared `session_context.mako` into per-profile templates
- Audit shared template for accuracy — some sections describe web-only capabilities generically

### Simplify session start recovery doc

`session_start_recovery.md` still references SOPS. Update Step 3 to source
`devinfra/secrets/web_env.sh` directly.

### `env_script_exports` threading

`env_script_exports: str` is sourced at daemon startup (`main.py`), stored in `app.state`,
threaded through `handle_session_start()`, and written once to the session env file.
Now that profiles are standalone files and the daemon loads exactly one, the profile file
path is known and the exports string could be cached alongside the profile. Low priority —
the current threading works.

## TODOs

- Double env_script resolution on laptop (direnv + daemon startup) — minor, second run is no-op
- `DUCKTAPE_DOCKER_CLIENT_KEY` disabled in `_common.sh` — `docker-ci.allegedly.works`
  unreachable from RBE workers. Tests use local Docker daemon. Re-enable when docker-ci
  works in cluster.
- `bbr.py` forwards `DUCKTAPE_DOCKER_CLIENT_KEY` via `--remote_run_header` which overrides
  `--test_env` — can't unset from inner bazel flags alone, must unset before bbr invocation.

## Non-goals

- Replacing SOPS with another secret backend
- Changing the hook daemon architecture (UDS, per-session state, FastAPI)
- Rewriting the proxy/BES interceptor

## Open Questions

- **Kubeconfig stays in session start**: depends on `combined_ca` from proxy setup — fine, just noting the split
