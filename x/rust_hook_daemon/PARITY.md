# Hook Daemon Feature Parity: Python vs Rust

Reference: Python `devinfra/claude/hook_daemon/`, Rust
`devinfra/claude/claude_hook/`. Selector:
`web_setup.sh --impl=<python|rust>` (default `python`).

## Process model

| Feature                                     | Python                                                 | Rust                                      |
| ------------------------------------------- | ------------------------------------------------------ | ----------------------------------------- |
| Runtime                                     | CPython 3.13, FastAPI/Uvicorn                          | Tokio + axum                              |
| Distribution                                | `claude-hooks` wheel (`uv tool install`)               | Static binary in Nix derivation           |
| Daemon spawn                                | Double-fork from client                                | Double-fork from client                   |
| Re-exec in grandchild                       | Yes                                                    | Yes (could be skipped, see PLAN.md gap 4) |
| IPC                                         | UDS (FastAPI/uvicorn over UDS)                         | UDS (axum + hyper TokioIo)                |
| Daemon runtime dir (pidfile, logs)          | `~/.claude/session-env/<sid>/hook-daemon/`             | `/tmp/claude-hd/<sid>/`                   |
| Home session dir (env file, bazelrc, shims) | `~/.claude/session-env/<sid>/`                         | `~/.claude/session-env/<sid>/`            |
| UDS socket path                             | `/tmp/claude-hd/<sid>/d.sock` (AF_UNIX 108-byte limit) | `/tmp/claude-hd/<sid>/d.sock`             |
| Idle watchdog (web only)                    | Yes (30 min default)                                   | Yes                                       |
| Daemon lock / single-instance               | pidfile + socket check                                 | pidfile + socket check                    |

## Wire protocol endpoints

| Endpoint          | Python | Rust |
| ----------------- | ------ | ---- |
| `POST /hook`      | ✅     | ✅   |
| `POST /shim-exec` | ✅     | ✅   |
| `POST /mailbox`   | ✅     | ✅   |
| `GET /health`     | ✅     | ✅   |

## Hook events handled

The PostToolUse pre-commit/lint runner and the PreToolUse permission stub were
removed in #1512 — both events now do mailbox drain only on both impls. #1515
adds an explicit `PreToolUse | PostToolUse` arm in the Rust dispatch match for
parity with the Python side.

| Event                                                                    | Python                      | Rust             |
| ------------------------------------------------------------------------ | --------------------------- | ---------------- |
| `SessionStart`                                                           | ✅ full setup               | ✅ full setup    |
| `PreToolUse`                                                             | ✅ mailbox drain            | ✅ mailbox drain |
| `PostToolUse`                                                            | ✅ mailbox drain            | ✅ mailbox drain |
| `WorktreeCreate`                                                         | ✅ `handle_worktree_create` | ❌ noop          |
| `UserPromptSubmit`, `Stop`, `SubagentStop`, `Notification`, `PreCompact` | mailbox drain               | mailbox drain    |
| Mailbox → systemMessage on REPL hooks                                    | ✅                          | ✅               |

## SessionStart setup steps

| Step                                                         | Python                                                          | Rust                                   |
| ------------------------------------------------------------ | --------------------------------------------------------------- | -------------------------------------- |
| Source `startup_env_script` (decrypt SOPS secrets)           | ✅                                                              | ✅                                     |
| Write env file (0o600) for Bash tool inheritance             | ✅                                                              | ✅                                     |
| Install PATH shims (`bazelisk`, `bazel`, `bb`, `bbr`, `git`) | ✅                                                              | ✅                                     |
| Write session `bazelrc` (JVM truststore, BES, cache)         | ✅                                                              | ✅                                     |
| Write `bbr.bazelrc` (BuildBuddy session tag)                 | ✅                                                              | ✅                                     |
| Write `buildbuddy.bazelrc` (API key)                         | ✅                                                              | ✅                                     |
| Launch `background_commands` (immediate + after-env)         | ✅                                                              | ✅                                     |
| Render context banner (`additionalContext`)                  | ✅ (Mako per-profile template)                                  | ✅ (hardcoded format; PLAN gap 1)      |
| Connectivity probe to `remote.buildbuddy.io`                 | ✅                                                              | ❌                                     |
| Container runtime setup (supervisor + Docker, web)           | ✅                                                              | ❌                                     |
| Tmpfs mount for Bazel cache (web/gVisor)                     | ✅                                                              | ❌                                     |
| Platform detection (Firecracker vs gVisor vs CLI)            | ✅                                                              | partial (root fstype + microvm cgroup) |
| BES interceptor (gRPC over UDS, forwards build events)       | ✅                                                              | ❌                                     |
| OTEL tracing init + spans                                    | ✅                                                              | ❌ (PLAN gap 3)                        |
| `kubectl-local` MCP wiring (kubeconfig in memfd)             | ✅ (separate `kubectl_local_mcp.py` binary, both impls call it) | ✅ (same external binary)              |

## Shim runtime

| Shim       | Python behavior                                                                | Rust behavior                               |
| ---------- | ------------------------------------------------------------------------------ | ------------------------------------------- |
| `git`      | Block `add -A`/`add .`, `stash` (push), `commit --amend` per `git_shim` config | Same policy, parsed by `git_shim::evaluate` |
| `bazelisk` | Inject `--bazelrc=<session bazelrc>` if exists                                 | Same                                        |
| `bazel`    | Inject `--bazelrc=<session bazelrc>` if exists                                 | Same                                        |
| `bb`       | Passthrough                                                                    | Passthrough                                 |
| `bbr`      | Passthrough                                                                    | Passthrough                                 |

## Profile / config

| Aspect                       | Python                 | Rust                                                                             |
| ---------------------------- | ---------------------- | -------------------------------------------------------------------------------- |
| Profile YAML schema          | Pydantic (`config.py`) | serde (`config.rs`)                                                              |
| `cli` profile                | ✅                     | reads same YAML, web-only fields ignored                                         |
| `web` profile                | ✅                     | reads same YAML, but web-only features (proxy, container, tmpfs, BES, OTEL) noop |
| Per-profile context template | ✅ (Mako)              | ❌ (PLAN gap 1)                                                                  |
| `git_shim` config            | ✅                     | ✅                                                                               |
| `otel` config                | ✅                     | ❌                                                                               |
| `background_commands`        | ✅                     | ✅                                                                               |
| `idle_watchdog`              | ✅                     | ✅                                                                               |

## Tests

| Test surface                               | Python                             | Rust                                       |
| ------------------------------------------ | ---------------------------------- | ------------------------------------------ |
| Container E2E (happy path)                 | ✅ (parameterized with both impls) | ✅                                         |
| Mailbox delivery E2E (`Pre`/`PostToolUse`) | ✅ (`python` parameterization)     | ✅ (`rust` parameterization, same test)    |
| Daemon restart / crash                     | ✅ `test_hook_daemon_restart`      | ❌ (PLAN gap 6)                            |
| Ensure-daemon double-fork race             | ✅ `test_ensure_daemon`            | partial (`daemon_lifecycle.rs` unit tests) |
| Shim unit tests                            | ✅ `test_shim`                     | ✅ (`shim_runtime.rs`, `git_shim.rs`)      |
| Background output staging                  | ✅ `test_bg_output`                | partial                                    |
| Tracing                                    | ✅ `test_tracing`                  | ❌                                         |

## Cutover blockers

Per <PLAN.md> and <CUTOVER_CHECKLIST.md>, before flipping
the default from Python to Rust:

1. OpenTelemetry tracing.
2. Per-profile context Mako/Tera template.
3. Web-profile services not yet ported: connectivity probe, container
   runtime / supervisor, tmpfs, BES interceptor. Rust today is effectively
   CLI-profile-complete only.
4. Restart/crash test parity.
