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

## Remaining

### CI workflow deduplication

Create `.github/actions/setup-ci-env` composite action wrapping Nix + devtools + secrets + optional Bazel setup. Extract image digest pinning into reusable action.

**Inconsistencies to fix**: missing `setup-bazel` in `push-images.yml`/`release.yml`, inline Python setup in `ansible-lint.yml`, stale `actions/checkout@v4` in `freecad-test-image.yml`.

### Profile config consolidation

Move remaining top-level `HookConfig` fields into `ProfileConfig`:

1. **Move `otel`, `pre_commit`, `k8s` into profile**: These are currently shared across
   profiles but should be per-profile (e.g. different pre-commit strictness for cli vs web,
   or different k8s clusters).
2. **One YAML file per profile**: Replace the `profiles:` dict in `config.yaml` with
   standalone files (e.g. `.claude_hooks/web.yaml`, `.claude_hooks/cli.yaml`). Each file
   is a complete `ProfileConfig` — no top-level `HookConfig` wrapper.
3. **`DUCKTAPE_CLAUDE_HOOKS_PROFILE` selects the file**: Set to a repo-relative path
   (e.g. `.claude_hooks/web.yaml`). In web mode, set as a session-level env var in Claude
   Code web configuration. In CLI mode, set in `.envrc`. The daemon loads exactly one
   profile file at startup — no profile resolution logic, no `default_profiles` map.
4. **Delete `HookConfig`**: Once profiles are standalone files, the top-level config
   wrapper and `resolve_profile()` become unnecessary.
5. **Daemon startup simplifies to**: load single profile YAML (path from env var) →
   source `env_script` → init OTEL tracing → start uvicorn. No profile resolution,
   no `is_web_mode()`, no `default_profiles` map. `create_app` takes the loaded profile
   directly — `web_mode` / profile caching in `app.state` become moot since there's
   only one profile and it's the whole config.

**Considered and rejected**: deferring env_script/OTEL init to first request (e.g. via
stdin bootstrap). The current startup is fast (no network calls), and deferring would add
conditional "not yet ready" states and a second protocol path for one-time use. The real
simplification comes from eliminating profile resolution, not from reordering init.

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

`session_context.mako` renders the same context blurb regardless of profile, but the
environment differs meaningfully between cli and web: different kubeconfig (personal vs
`claude-sandbox` SA), different GitHub token (personal PAT vs machine-user PAT), different
RBAC scope. The template should reflect what the agent actually has access to, not a
generic "secrets loaded" message.

Approach: add an optional `context_template` field to `ProfileConfig` — a Mako snippet
(inline string or repo-relative `.mako` file) rendered into the session context output.
Each profile describes its own environment. The shared `session_context.mako` handles
structural sections (proxy, docker, warnings) and delegates the profile-specific block
to the profile's template. The current template should also be audited for accuracy — it
describes capabilities (k8s access, secrets, Docker) that differ between cli and web but
are rendered identically.

### Simplify session start recovery doc

`devinfra/claude/hook_daemon/docs/session_start_recovery.md` still references SOPS
decryption, `sops_decrypt.py`, and manual secret assembly. With env scripts
(`devinfra/secrets/*.sh`), Step 3 (manual assembly) simplifies to sourcing the env script
directly: `source devinfra/secrets/web_env.sh` gives you `BUILDBUDDY_API_KEY`,
`GITHUB_TOKEN`, etc. without the SOPS Python API dance. Update the doc to reflect this.

### Shim handler: fix dummy session_id and extract per-shim logic

The `/shim-exec` handler in `server.py` has two issues:

1. **Dummy session*id `"*"`**: `SessionPaths.from_env("_", report.env)` is called just to
   get `paths.bazelrc`, which is `<session_dir>/bazelrc`. Should read
   `DUCKTAPE_CLAUDE_HOOKS_SESSION_DIR` from `report.env` directly and construct the path
   without faking a session ID.

2. **Inline per-shim logic**: The handler does proxy creds + git blocking + bazelisk flag
   injection all inline behind `if report.shim == "git"` / `"bazelisk"` checks. Extract
   per-shim handlers as a `dict[str, Callable]` dispatch so adding a new shim doesn't
   require editing the main handler. Each shim handler takes `(report, argv)` and returns
   `ShimBlocked | ShimExecve`.

### `env_script_exports` threading

`env_script_exports: str` is sourced at daemon startup (`main.py`), stored in `app.state`,
threaded through `handle_session_start()`, and written once to the session env file. It
can't be deferred to session start because the env script also populates `os.environ` with
`DUCKTAPE_OTEL_BEARER_TOKEN` (needed for OTEL tracer init before uvicorn starts) and
`BUILDBUDDY_API_KEY` (read from `os.environ` at session start). The raw export lines are a
separate concern — once profiles are standalone files and the daemon loads exactly one
profile, this threading simplifies naturally (the profile file path is known, the script
can be re-sourced if needed, and the exports string can be cached alongside the profile).

## TODOs

- Double env_script resolution on laptop (direnv + daemon startup) — minor, second run is no-op
- Container e2e test: env script passthrough verified (E2E_TEST_SECRET in session env file).
  Shim refactor replaced `wrappers/bazel.py` with `wrappers/bazelisk.py` — wheel packaging
  may need updating for new module paths. Awaiting green run.
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
