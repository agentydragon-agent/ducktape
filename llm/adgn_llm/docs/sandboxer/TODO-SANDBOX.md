# TODO — Sandbox Hardening and Options (Plan + Progress)

This document now contains both the plan/todos and the progress log. The historical PROGRESS_LOG.md has been merged here for a single source of truth.

- Network egress options:
  - Add a mode to allow only loopback + a local HTTP proxy, and restrict that proxy to a curated allowlist (e.g., openai.com) while denying general HTTP
- Filesystem surface:
  - Reduce file-read* to the minimum required (system libs, site-packages) and keep WORKSPACE read/write; make /tmp writes optional
- Policy capabilities:
  - Support specifying policy sections/capabilities on argv (seatbelt substitutions), to toggle features without changing code
- Environment hygiene:
  - Allow only a curated set of env vars to reach the kernel; strip the rest by default, with an opt-in allowlist

---

# Target design notes (agreed direction)

Components and names
- Tool 1 (YAML → platform sandbox runner): sandboxer
  - Purpose: execute a command under a sandbox defined by explicit YAML; demux to seatbelt (macOS) or bwrap (Linux)
  - Net proxy mode: sandboxer manages an HTTP proxy lifecycle (spawn, configure allowlist, set proxy env inside sandbox, teardown)
  - Windows: unsupported; fail fast if platform not macOS/Linux
- Tool 2 (Jupyter MCP server+bridge launcher): jupyter-mcp-launch
  - Purpose: start Jupyter Server with a fixed config dir, then jupyter-mcp-server (stdio). No sandbox logic.
  - Assumes kernelspec argv wraps the kernel via sandboxer
- Composer (one-time bundle builder): jupyter-sandbox-compose
  - Purpose: produce a relocatable control bundle with config, kernels, and policies (profiles like low/high privilege)
  - Must include "jupyter" in the name (done)

Policy YAML (explicit-only, platform-selective)
- env:
  - set: { JUPYTER_* dirs, HOME, PYTHONPYCACHEPREFIX, MPLCONFIGDIR, PATH prepend for control venv }
  - passthrough: [OPENAI_API_KEY, HTTP_PROXY, HTTPS_PROXY, ...]
- fs:
  - allow_write_all: bool
  - allow_read_all: bool
  - read_paths: [abs paths]
  - write_paths: [abs paths]
- net:
  - mode: none | loopback | all | allowlist | proxy
  - allow_domains: [api.openai.com, ...] (for allowlist/proxy modes)
  - proxy: { listen: 127.0.0.1:0, upstream: null | host:port }
- platform:
  - seatbelt: { trace: bool, extra_allow: { mach-lookup: [..], system-socket: bool, dev: { allow_tty_writes: bool }, file_read_extra: [subpaths] } }
  - bwrap: { ro_bind: [...], rw_bind: [...], tmpfs: [...], unshare: { net: bool, pid: bool, ipc: bool }, devices: [null, urandom, random] }

Notes
- On Linux, bwrap ro_bind/rw_bind will be derived largely from generic fs.read_paths/write_paths; platform.bwrap allows extra mounts/tuning as needed.
- Docker: orthogonal; configs differ enough that unifying with sandboxer isn’t worth it. Leave as a separate composer flow (TODO).
- Future: a "sandboxer MCP" that accepts "execute <foo> under sandbox <bar>" with internal policies (e.g., only allow <baz> if net=none and specific read-only areas), with agent request → user approve/deny flow. Leave as TODO.

Directory layout (example control bundle)
- control/
  - bin/ (control venv: jupyter, jupyter-mcp-server, sandboxer)
  - jupyter/config/jupyter_server_config.py
  - kernels/
    - python3-low/kernel.json  # argv: sandboxer --policy policies/low/policy.yaml -- <kernel-python> -m ipykernel_launcher -f {connection_file}
    - python3-high/kernel.json
  - policies/
    - low/policy.yaml
    - high/policy.yaml
  - mcp/
    - jupyter_mcp_launcher.yaml (optional convenience)

---

# Implementation plan and todos

MVP phase 1 — carve and scaffold
- [x] Choose and lock names: sandboxer (tool1), jupyter-mcp-launch (tool2), jupyter-sandbox-compose (composer)
- [x] Implement sandboxer (macOS seatbelt backend only)
  - [x] Parse YAML (env/set, env/passthrough, fs, net, platform.seatbelt) with Pydantic model
  - [x] Compose seatbelt .sb (deny default; base primitives; FS allowlists from fs.*; optional trace; platform extras)
  - [x] Net: implement modes none|loopback|all (allowlist/proxy deferred)
  - [x] Exec target command under sandbox-exec -f <rendered.sb>
- [x] Implement jupyter-mcp-launch (no sandbox logic)
  - [x] Args: --config, --kernels, --workspace, [--kernel-name], [--port 0], [--token auto], [--start-new-runtime]
  - [x] Start Jupyter Server with given config dir; pick free port if 0; write logs
  - [x] Start jupyter-mcp-server (stdio); tee logs
- [x] Implement jupyter-sandbox-compose (bootstrap)
  - [x] Create control bundle directories; rely on pre-installed control venv
  - [x] Write jupyter_server_config.py (ensure_native_kernel=False, ip=127.0.0.1, disable_check_xsrf=True)
  - [x] Emit profiles: policies/{low,high}/policy.yaml
  - [x] Emit kernels/{python3-low,python3-high}/kernel.json (argv uses sandboxer)

Phase 2 — functionality hardening
- [ ] Add sandboxer proxy-managed allowlist mode (net: proxy)
  - [ ] Spawn local HTTP proxy on 127.0.0.1:0; set HTTP(S)_PROXY inside sandbox; filter by allow_domains
  - [ ] Teardown proxy cleanly on exit
- [ ] Add Linux bwrap backend
  - [ ] Map fs.read_paths → ro binds; fs.write_paths → rw binds; tmpfs per policy
  - [ ] Implement net: none via unshare; loopback-only TBD; proxy mode supported via same proxy flow
- [ ] Tighten macOS base allowances (mach-lookup/system-socket/dev/tty) guided by traces
- [ ] Fonts/plotting support: add curated read paths for macOS fonts and fontconfig caches if needed

Phase 3 — integration and migration
- [ ] Update docs to reflect new tools and composer
- [ ] Provide migration path from current wrapper to tool2+composer
- [ ] Extend tests to cover sandboxer seatbelt policies and jupyter-mcp-launch happy paths
- [ ] Leave Docker as TODO: evaluate a separate docker-compose-like flow

Future (tracked, not in MVP)
- [ ] Sandboxer MCP (agent-facing): accept "execute under sandbox X" with user policy gates and approval flow; dynamic tweaks
- [ ] Richer Jupyter MCP (multi-notebook, multi-kernel lifecycle)

Status tracking
- Use the progress log below; update as tasks complete. Add trace-driven findings and decisions with timestamp+sha.

---

# Progress Log (merged from PROGRESS_LOG.md)

- Timestamp: 2025-08-27T03:48:10Z
- Repo SHA: 8f7b80b23c76

## Update

- Policy model refactor (explicit-only):
  - Removed global `file-read*` from base seatbelt profile; reads now explicit via `allow_read_all`/`read_paths`.
  - `allow_write_all` implies read and is mutually exclusive with `read_paths`.
  - No implicit workspace/run_root write roots; empty lists are respected.
  - Required CLI flags: `--workspace`, `--run-root`, `--kernel-python`.
  - `env_passthrough` added (kept empty by default).
- Control venv pattern:
  - Dedicated control venv for `jupyter-server` + `jupyter-core` + `jupyter-mcp-server` (outside kernel venv).
  - Tests bootstrap this venv automatically and prepend it on PATH; removed HOME passthrough from tests.
  - Worktree setup now creates this control venv under `$WT_DIR/<worktree>/config/jupyter_control_venv` and points `.mcp.json` to its `sandbox-jupyter-mcp`.
- Jupyter config hardening:
  - Stop defaulting JUPYTER_* dirs in the wrapper; policy env now sets them explicitly to run_root paths.
  - Dropped `default_kernel_name` traits to avoid `notebook_shim` trait errors.
- Diagnostics:
  - New `--debug-diag` flag (or `SJ_DEBUG_DIAG=1`) prints child PATH, resolved binaries, versions, and kernel python during init.
- Docs:
  - README: now points to `sandboxed_jupyter_example/` for a per-repo, less‑wiggly setup with tables.
  - Example shows minimal control venv install (no Lab/Notebook required) and fully explicit policy examples.

## Next (from earlier)

- Implement network policy enforcement (`net`) with modes (none/loopback/allowlist/proxy) in seatbelt profile.
- Flip remaining tests to `allow_read_all: false` and tighten `read_paths` using trace‑driven allowlisting (site‑packages + repo).
- Review and remove unnecessary base allowances (mach-lookup/system-socket, `/dev/tty` writes) once kernel/jupyter behavior is verified.

2025-08-27T05:46:08Z sha=8f7b80b23c76: Split into sandboxer/jupyter-mcp-launch/jupyter-sandbox-compose; composer+launcher smoke OK; fixed IdentityProvider.token; removed kernel_dirs; next: proxy allowlist, bwrap backend, tighten base allowances.

2025-08-27T07:31:47Z sha=8f7b80b23c76: Consolidated websocket settings to config-only (no CLI); documented benign clamp warning; removed kernel_dirs; tools split (sandboxer/jupyter-mcp-launch/jupyter-sandbox-compose) smoke OK; killed stray smoke shells; next: implement sandboxer net: proxy allowlist and add bwrap backend; update docs.
