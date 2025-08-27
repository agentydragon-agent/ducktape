# Progress Log — Jupyter MCP STDIO Guard

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

## Next

- Implement network policy enforcement (`net`) with modes (none/loopback/allowlist/proxy) in seatbelt profile.
- Flip remaining tests to `allow_read_all: false` and tighten `read_paths` using trace‑driven allowlisting (site‑packages + repo).
- Review and remove unnecessary base allowances (mach-lookup/system-socket, `/dev/tty` writes) once kernel/jupyter behavior is verified.
