# STDIO Mode — Current CLI (explicit policy)

This wrapper exposes a stdio MCP server that drives a local Jupyter Server. Kernels run under macOS seatbelt (sandbox-exec) using an explicitly composed policy; the Jupyter Server itself runs unsandboxed on 127.0.0.1.

Key points (current implementation):
- Subcommand: `stdio` (there is no `--stdio-server` flag)
- Required flags: `--policy-config`, `--workspace`, `--run-root`, `--kernel-python`
- Policy model is explicit-only: allow_read_all, allow_write_all, read_paths, write_paths, env, env_passthrough
- No default_kernel_name traits are set; Jupyter is locked to use only our kernelspec directory and to disable native kernels
- The synthetic notebook created by the wrapper declares kernelspec name "python3"; the wrapper provides a sandboxed "python3" kernelspec under RUN_ROOT

## Quick start

```bash
/absolute/path/to/sandbox-jupyter-mcp stdio \
  --policy-config "/abs/policy.yaml" \
  --workspace "/abs/repo" \
  --run-root "/tmp/sjmcp_run" \
  --kernel-python "/abs/venv/bin/python" \
  --trace-sandbox \
  --debug-diag
```

If you omit `--document-id`, a new notebook is created under `<workspace>/.mcp/scratch/<timestamp>-<rand>.ipynb` with kernelspec `{name: "python3"}`.

## Behavior

- Jupyter Server
  - Launched on 127.0.0.1 with a random free port (or `--jupyter-port` if provided)
  - Logs written to `<run_root>/runtime/jupyter_server.{out,err}`
  - Config written to `<run_root>/config/jupyter_server_config.py` with:
    - `KernelSpecManager.kernel_dirs = ['<run_root>/data/kernels']`
    - `KernelSpecManager.ensure_native_kernel = False`
    - `ServerApp.open_browser = False`, `ip='127.0.0.1'`, `disable_check_xsrf=True`
- Kernel sandbox
  - Seatbelt policy composed from your YAML and saved to `<run_root>/policy.sb`
  - A sandboxed kernelspec is written to `<run_root>/data/kernels/python3/kernel.json` with argv:
    - `sandbox-exec -f <policy.sb> <kernel-python> -m ipykernel_launcher -f {connection_file}`
  - A `kernels.json` is written under `<run_root>/runtime` to hint default="python3" for new documents
- MCP stdio
  - `jupyter-mcp-server start --transport stdio --provider jupyter ...` is executed with PATH resolved from the child env
  - Streams are tee’d to `<run_root>/mcp_stdout.log` and `<run_root>/mcp_stderr.log`
- Diagnostics
  - With `--debug-diag` (or `SJ_DEBUG_DIAG=1`), versions/paths of `jupyter`, `jupyter server`, `jupyter-mcp-server`, and the kernel Python are printed to stderr
  - With `--trace-sandbox`, seatbelt `(trace ...)` is enabled and the trace path is printed to stderr

## Policy YAML (schema)

```yaml
# policy.yaml
allow_read_all: false
allow_write_all: false
read_paths:
  - /abs/repo/.venv/lib/python3.12/site-packages   # example: kernel venv site-packages
  - /abs/repo                                       # example: repo (read-only)
write_paths:
  - /abs/repo                                       # workspace writes
  - /tmp/sjmcp_run                                   # run-root writes
env:
  # Jupyter dirs (recommended)
  JUPYTER_RUNTIME_DIR: /tmp/sjmcp_run/runtime
  JUPYTER_DATA_DIR: /tmp/sjmcp_run/data
  JUPYTER_CONFIG_DIR: /tmp/sjmcp_run/config
  JUPYTER_PATH: /tmp/sjmcp_run/data
  # Python caches and matplotlib
  PYTHONPYCACHEPREFIX: /tmp/sjmcp_run/pycache
  MPLCONFIGDIR: /tmp/sjmcp_run/mpl
  # Recommended HOME isolation
  HOME: /tmp/sjmcp_run
  # Ensure control venv precedes on PATH if applicable
  PATH: /abs/control_venv/bin:${PATH}
env_passthrough: []  # add explicit names to import from parent env (e.g., OPENAI_API_KEY)
```

Notes:
- The wrapper does not implicitly set these env vars; you must provide the ones you want via `env`.
- `allow_write_all` implies read and is incompatible with non-empty `write_paths`/`read_paths`.
- `allow_read_all` is incompatible with non-empty `read_paths`.
- `net` is present in the schema for future enforcement (modes like `none`, `loopback`, `allowlist:...`, `proxy:...`) but is not enforced yet.

## FAQ

- Does default_kernel_name matter?
  - No. The wrapper does not set it. The synthetic notebook declares `python3`, and Jupyter is configured to only see our kernelspec directory with native kernels disabled. Therefore the notebook’s kernelspec name drives selection.
- Where do logs go?
  - Jupyter: `<run_root>/runtime/jupyter_server.{out,err}`
  - MCP stdio: `<run_root>/mcp_stdout.log`, `<run_root>/mcp_stderr.log`
- How is `jupyter-mcp-server` found?
  - Resolved using the child environment’s PATH (constructed from your YAML `env` plus `env_passthrough`).
