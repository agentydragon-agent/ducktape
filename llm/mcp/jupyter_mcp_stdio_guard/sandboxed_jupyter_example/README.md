# Sandboxed Jupyter MCP — per‑repo setup example

This guide shows how to run a per‑git‑repo Jupyter server whose kernels run inside a macOS seatbelt (or Docker) sandbox, exposed via the Jupyter MCP Server. It matches the “explicit policy, zero magic” model and uses uv tool install for jupyter-mcp-server so it stays outside your kernel venv.

Audience: “I want each repo to have its own sandboxed Jupyter environment wired via repo/.mcp.json, with a dedicated kernel venv.”

## Summary
- Install jupyter-mcp-server as a uv tool (outside your repo/kernel venv)
- Create per‑repo sandbox dirs and an explicit policy.yaml (no implicit allow‑all)
- Launch the wrapper via .mcp.json using required flags: --policy-config, --workspace, --run-root, --kernel-python
- Ensure PATH includes ~/.local/bin so jupyter-mcp-server is found by the child process

## 0) Requirements
- macOS (seatbelt: sandbox-exec) or Docker available
- Python 3.11+ and uv installed
- A kernel venv per repo (your code and ipykernel go here)

## 1) Install MCP server as a uv tool (outside the kernel venv)
```bash
uv tool install jupyter-mcp-server
# Verify the shim is on PATH
command -v jupyter-mcp-server
```
This places a stable shim at ~/.local/bin/jupyter-mcp-server and manages its runtime env under ~/.cache/uv. It avoids mixing MCP server deps with your kernel venv (which may have incompatible pins).

Optional: install Jupyter CLI similarly if you don’t have it:
```bash
# Option A (recommended for stability): create a dedicated control venv and pin versions
python3 -m venv .venv_jupyter
./.venv_jupyter/bin/pip install -U pip wheel
./.venv_jupyter/bin/pip install \
  jupyter-server jupyter-core jupyter-mcp-server

# Option B (shim only): uv tool install just the launcher
uv tool install jupyter-core  # provides the `jupyter` launcher on PATH
```

## 1.5) Components and where they live (less wiggly)

| Component | Role | Runs inside | Install location | How to install | Notes |
|---|---|---|---|---|---|
| sandbox-jupyter-mcp (wrapper) | Orchestrates Jupyter + MCP; generates seatbelt policy; launches kernel sandbox | Outside kernel sandbox | Your repo (invoked via .mcp.json) | n/a | Provide flags: --policy-config, --workspace, --run-root, --kernel-python |
| Jupyter server (CLI: `jupyter`) | HTTP server for notebooks/runtime | Outside kernel sandbox | Control venv (e.g. ./.venv_jupyter) or system | pip install jupyter-server jupyter-core | Put control venv/bin first in PATH inside policy env |
| jupyter-mcp-server | MCP bridge (stdio) that talks to the Jupyter server | Outside kernel sandbox | Control venv (./.venv_jupyter) or uv tool (~/.local/bin) | pip install jupyter-mcp-server into ./.venv_jupyter OR uv tool install jupyter-mcp-server | Keep outside the kernel venv to avoid dependency conflicts; pin version if installed in control venv |
| Kernel Python + your code | Executes notebook cells | Inside seatbelt/Docker sandbox | Repo venv (e.g. ./.venv) | pip install ipykernel and your deps | Pass via --kernel-python=./.venv/bin/python |
| sandbox-exec (macOS) | Seatbelt enforcement | Kernel only | System | preinstalled on macOS | Wrapper uses it for the kernelspec |

Two stable setups:
- Most hermetic: Control venv for both Jupyter server and jupyter-mcp-server; kernel venv for your code. No uvx/uv tool at runtime.
- Alternative: Control venv for Jupyter server + uv tool for jupyter-mcp-server; kernel venv separate.

### Packages by environment (pinning for less wiggle)

| Environment | Runs | Packages (pin where shown) | Install | PATH inside policy env |
|---|---|---|---|---|
| Control venv (./.venv_jupyter) | Jupyter server (outside sandbox) | jupyter-server, jupyter-core | pip install into ./.venv_jupyter | Prepend: ./.venv_jupyter/bin:$HOME/.local/bin:$PATH |
| uv tool (~/.local/bin) | jupyter-mcp-server (outside sandbox) | jupyter-mcp-server | uv tool install jupyter-mcp-server | Ensure $HOME/.local/bin is in PATH |
| Kernel venv (./.venv) | Notebook kernel (inside sandbox) | ipykernel + your repo deps | pip install into ./.venv | Passed via --kernel-python=./.venv/bin/python |
| System | macOS seatbelt | sandbox-exec | preinstalled | n/a |

Notes
- Jupyter server can live in the wrapper’s venv instead of a dedicated control venv; the key is: keep jupyter-mcp-server outside the kernel venv and ensure the server binary is first on PATH.
- Avoid uvx inside the sandbox; if you must, set UV_CACHE_DIR to a writeable path under run_root to keep runs deterministic.

## 2) Per‑repo directory layout
Create these under your repo root:
```
repo/
  config/sandboxed_jupyter/
    workspace/           # Server root_dir (notebooks live here)
    run_root/            # Runtime/logs/temp/cache
    policy.yaml          # Explicit sandbox policy (see below)
  .mcp.json              # MCP client wiring
```

## 3) Explicit policy.yaml (no magic)
Schema the wrapper expects:
- allow_read_all: bool
- allow_write_all: bool
- read_paths: list[str]
- write_paths: list[str]
- env: dict[str,str]
- env_passthrough: list[str]

Notes
- No implicit write roots. Empty lists are respected.
- Write implies read (allow_write_all=true requires read_paths=[]).
- Net is TODO (Jupyter binds 127.0.0.1); further net policies to come.

Example A — strict (get started, narrow later)
```yaml
allow_read_all: true
allow_write_all: false
read_paths: []
write_paths:
  - ./config/sandboxed_jupyter/workspace
  - ./config/sandboxed_jupyter/run_root
env:
  # Ensure the child can find jupyter-mcp-server installed via uv tool
  PATH: "$HOME/.local/bin:$PATH"
  # Make Jupyter’s runtime/data/config explicit and confined to run_root
  JUPYTER_RUNTIME_DIR: ./config/sandboxed_jupyter/run_root/runtime
  JUPYTER_DATA_DIR: ./config/sandboxed_jupyter/run_root/data
  JUPYTER_CONFIG_DIR: ./config/sandboxed_jupyter/run_root/config
  MPLCONFIGDIR: ./config/sandboxed_jupyter/run_root/mpl
  PYTHONPYCACHEPREFIX: ./config/sandboxed_jupyter/run_root/pycache
  TMPDIR: ./config/sandboxed_jupyter/run_root/tmp
  PYTHONUNBUFFERED: "1"
# Minimal passthrough; if you use uvx for anything in the child, prefer:
# UV_CACHE_DIR: ./config/sandboxed_jupyter/run_root/uv_cache
env_passthrough: []
```

Example B — fully explicit reads (no global read)
```yaml
allow_read_all: false
allow_write_all: false
read_paths:
  - .  # repo root, or narrower: ./src, ./notebooks
  - /absolute/path/to/your/kernel/venv  # for site-packages if needed
write_paths:
  - ./config/sandboxed_jupyter/workspace
  - ./config/sandboxed_jupyter/run_root
env:
  PATH: "$HOME/.local/bin:$PATH"
  JUPYTER_RUNTIME_DIR: ./config/sandboxed_jupyter/run_root/runtime
  JUPYTER_DATA_DIR: ./config/sandboxed_jupyter/run_root/data
  JUPYTER_CONFIG_DIR: ./config/sandboxed_jupyter/run_root/config
  MPLCONFIGDIR: ./config/sandboxed_jupyter/run_root/mpl
  PYTHONPYCACHEPREFIX: ./config/sandboxed_jupyter/run_root/pycache
  TMPDIR: ./config/sandboxed_jupyter/run_root/tmp
  PYTHONUNBUFFERED: "1"
env_passthrough: []
```
Tip: Start with allow_read_all: true to validate the flow, then narrow read_paths to only what’s needed (repo root + your kernel venv). Avoid passing HOME; pin and preinstall tools to keep runs hermetic.

## 4) .mcp.json wiring (per‑repo)
Place this at repo/.mcp.json:
```json
{
  "mcpServers": {
    "sandboxed_jupyter": {
      "command": "sandbox-jupyter-mcp",
      "args": [
        "stdio",
        "--policy-config=./config/sandboxed_jupyter/policy.yaml",
        "--workspace=./config/sandboxed_jupyter/workspace",
        "--run-root=./config/sandboxed_jupyter/run_root",
        "--kernel-python=./.venv/bin/python"
      ],
      "env": {}
    }
  }
}
```
- --kernel-python should point at your repo’s kernel venv (where ipykernel and your code live).
- The wrapper will enforce the seatbelt policy for kernel processes; the Jupyter server runs loopback‑only and uses the run_root dirs you specify.

## 5) Create a kernel venv per repo
```bash
python3 -m venv .venv
./.venv/bin/pip install -U pip wheel
./.venv/bin/pip install ipykernel
# plus your repo’s Python deps
```

Optional: preinstall Jupyter CLI in this venv if you want to run it directly for debugging; it’s not required for MCP flow.

## 6) Smoke test
```bash
# Create a trivial notebook in workspace (wrapper will also create one if missing)
mkdir -p ./config/sandboxed_jupyter/workspace/.mcp/scratch
# Launch the wrapper directly (stdio transport)
SJ_DEBUG_DIAG=1 sandbox-jupyter-mcp stdio \
  --policy-config=./config/sandboxed_jupyter/policy.yaml \
  --workspace=./config/sandboxed_jupyter/workspace \
  --run-root=./config/sandboxed_jupyter/run_root \
  --kernel-python=./.venv/bin/python
# You should see: [wrapper] jupyter: http://127.0.0.1:PORT and MCP server starting
```

## 7) Narrow reads (recommended)
Once working, change allow_read_all: false and list only specific read_paths (e.g., your repo root and your kernel venv). Re‑run to ensure no unexpected read denials.

## 8) Docker mode (optional)
You can use --mode docker instead of seatbelt:
- workspace mounts at /workspace
- JUPYTER_* dirs are set inside the container to a temp run_root
- Kernel and MCP still run with the same policy.yaml semantics

## Troubleshooting
- “jupyter-mcp-server not found on PATH” → Ensure uv tool install placed it at ~/.local/bin and that policy env PATH includes $HOME/.local/bin:$PATH.
- Websocket 1002 protocol error on collaboration endpoint → Pin jupyter-server/jupyterlab/notebook and RTC extensions; avoid uvx inside the sandbox (preinstall outside), or set UV_CACHE_DIR to a writeable run_root path if you must use uvx.
- Trait errors for default_kernel_name / notebook_shim → Do not set default kernel traits; wrapper avoids them by default.

