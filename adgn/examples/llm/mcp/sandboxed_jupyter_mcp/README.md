# Sandboxed Jupyter MCP — per‑repo setup example (composer + launcher)

This example shows a per‑repo, sandboxed Jupyter setup exposed via the Jupyter MCP server using the split tools:
- sandboxer: applies an explicit seatbelt/bwrap policy to kernels (invoked via kernelspec argv)
- jupyter-sandbox-compose: generates a relocatable bundle (config/kernels/policies) from a single YAML
- jupyter-mcp-launch: launches Jupyter Server and jupyter-mcp-server (stdio) using the bundle

Why: keep your kernel venv (your code) fully separate from the control toolchain (Jupyter + MCP), and keep policy explicit‑only (no implicit read/write).

## What you need
- macOS (seatbelt) or Linux (bwrap coming later)
- Two virtualenvs:
  - Kernel venv (your repo): ipykernel + your deps
  - Control venv (outside repo): jupyter-server, jupyter-core, jupyter-mcp-server, adgn_llm.mcp.sandboxed_jupyter_mcp (editable install)

Install the control toolchain (example):
```bash
python3 -m venv ~/.venvs/jupyter_control
~/.venvs/jupyter_control/bin/pip install -U pip wheel
~/.venvs/jupyter_control/bin/pip install jupyter-server jupyter-core jupyter-mcp-server pyyaml 'pydantic>=2'
# Editable install via uv so the CLIs are available
~/.venvs/jupyter_control/bin/uv uv pip install -e adgn
```

Create the kernel venv in your repo and install ipykernel + your libs:
```bash
python3 -m venv .venv
./.venv/bin/pip install -U pip wheel ipykernel
# plus your repo deps
```

## Layout
We will generate a bundle (read‑only) and a runtime dir (writable) under your repo:
```
repo/
  sandboxed_jupyter_example/
    bundle/            # composer output (config/kernels/policies)
    runtime/           # writable runtime (HOME/tmp/caches)
  .mcp.json            # MCP wiring to jupyter-mcp-launch
```

## 1) Write the composer config (single YAML)
Composer accepts a single YAML input. You can pipe it on stdin; here’s a minimal example you can adjust:
```yaml
version: 1
bundle_dir: ./sandboxed_jupyter_example/bundle
runtime_dir: ./sandboxed_jupyter_example/runtime

kernel:
  name: python3
  display_name: Python 3 (sandboxed)
  language: python
  argv_base:
    - ./\.venv/bin/python
    - -m
    - ipykernel_launcher

# Optional: extra traitlets appended verbatim after defaults
jupyter:
  config_py_extra: |-
    # c.ServerApp.allow_remote_access = False

# Policy is passed through with minimal inserts:
# env.set: HOME, PYTHONPYCACHEPREFIX, MPLCONFIGDIR, TMPDIR/TMP/TEMP -> runtime_dir (if missing)
# fs.write_paths: [runtime_dir] (if missing)
# fs.read_paths: [kernel argv_base[0]] + macOS font dirs (if missing)
policy:
  env:
    set: {}
    passthrough: []
  fs:
    allow_read_all: false
    allow_write_all: false
    read_paths: []
    write_paths: []
  net:
    mode: loopback
  platform:
    seatbelt:
      trace: false
```

Run composer (stdin supported):
```bash
# From the repo root
cat sandboxed_jupyter_example/composer.yaml | \
  ~/.venvs/jupyter_control/bin/python -m adgn_llm.mcp.sandboxed_jupyter_mcp.jupyter_sandbox_compose --config -
```
This writes:
- sandboxed_jupyter_example/bundle/config/jupyter_server_config.py
- sandboxed_jupyter_example/bundle/policies/policy.yaml
- sandboxed_jupyter_example/bundle/kernels/python3/kernel.json

## 2) Wire MCP to the launcher
Place this .mcp.json at the repo root, pointing to the control venv python and the generated bundle:
```json
{
  "mcpServers": {
    "sandboxed_jupyter": {
      "type": "stdio",
      "command": "~/.venvs/jupyter_control/bin/python",
      "args": [
        "-m", "adgn_llm.mcp.sandboxed_jupyter_mcp.jupyter_mcp_launch",
        "--config", "./sandboxed_jupyter_example/bundle/config",
        "--kernels", "./sandboxed_jupyter_example/bundle/kernels",
        "--workspace", "./sandboxed_jupyter_example/runtime/workspace",
        "--kernel-name", "python3",
        "--port", "0",
        "--token", "auto",
        "--start-new-runtime",
        "--log-dir", "./sandboxed_jupyter_example/runtime"
      ],
      "env": {}
    }
  }
}
```
Notes:
- The launcher starts Jupyter server and jupyter-mcp-server (stdio) using the bundle.
- The kernelspec argv runs the sandboxer (control venv python) and then your kernel argv_base inside the sandbox.

## 3) Smoke test
- Open Claude Code in this repo; it will detect .mcp.json and offer the sandboxed_jupyter MCP.
- Or launch manually by running the "command" + "args" above from a shell.
- You should see the launcher print a localhost URL and then the MCP process start.

## 4) Tighten policy over time
Start with the minimal defaults; add read_paths and write_paths explicitly as you encounter denials. Keep runtime_dir as the only default write area; add project paths only as needed.

---

## Tests: reuse this example flow
The end‑to‑end workflow tests should:
1) Create a temp repo workspace and kernel venv (install ipykernel)
2) Write a composer YAML like the one above, pointing at temporary bundle/runtime paths
3) Run the composer via the control venv’s python (stdin supported)
4) Launch jupyter-mcp-launch with the generated bundle
5) Exercise a trivial notebook (e.g., execute `print(2+2)`) via MCP

This keeps tests and docs in sync by using the same entrypoints the example prescribes.

# Sandboxed Jupyter MCP — per‑repo setup example (composer + launcher)

This example shows a per‑repo, sandboxed Jupyter setup exposed via the Jupyter MCP server using the split tools:
- sandboxer: applies an explicit seatbelt/bwrap policy to kernels (invoked via kernelspec argv)
- jupyter-sandbox-compose: generates a relocatable bundle (config/kernels/policies) from a single YAML
- jupyter-mcp-launch: launches Jupyter Server and jupyter-mcp-server (stdio) using the bundle

Why: keep your kernel venv (your code) fully separate from the control toolchain (Jupyter + MCP), and keep policy explicit‑only (no implicit read/write).

## What you need
- macOS (seatbelt) or Linux (bwrap coming later)
- Two virtualenvs:
  - Kernel venv (your repo): ipykernel + your deps
  - Control venv (outside repo): jupyter-server, jupyter-core, jupyter-mcp-server, adgn_llm.mcp.sandboxed_jupyter_mcp (editable install)

Install the control toolchain (example):
```bash
python3 -m venv ~/.venvs/jupyter_control
~/.venvs/jupyter_control/bin/pip install -U pip wheel
~/.venvs/jupyter_control/bin/pip install jupyter-server jupyter-core jupyter-mcp-server pyyaml 'pydantic>=2'
# Editable install via uv so the CLIs are available
~/.venvs/jupyter_control/bin/uv uv pip install -e adgn
```

Create the kernel venv in your repo and install ipykernel + your libs:
```bash
python3 -m venv .venv
./.venv/bin/pip install -U pip wheel ipykernel
# plus your repo deps
```

## Layout
We will generate a bundle (read‑only) and a runtime dir (writable) under your repo:
```
repo/
  sandboxed_jupyter_example/
    bundle/            # composer output (config/kernels/policies)
    runtime/           # writable runtime (HOME/tmp/caches)
  .mcp.json            # MCP wiring to jupyter-mcp-launch
```

## 1) Write the composer config (single YAML)
Composer accepts a single YAML input. You can pipe it on stdin; here’s a minimal example you can adjust:
```yaml
version: 1
bundle_dir: ./sandboxed_jupyter_example/bundle
runtime_dir: ./sandboxed_jupyter_example/runtime

kernel:
  name: python3
  display_name: Python 3 (sandboxed)
  language: python
  argv_base:
    - ./\.venv/bin/python
    - -m
    - ipykernel_launcher

# Optional: extra traitlets appended verbatim after defaults
jupyter:
  config_py_extra: |-
    # c.ServerApp.allow_remote_access = False

# Policy is passed through with minimal inserts:
# env.set: HOME, PYTHONPYCACHEPREFIX, MPLCONFIGDIR, TMPDIR/TMP/TEMP -> runtime_dir (if missing)
# fs.write_paths: [runtime_dir] (if missing)
# fs.read_paths: [kernel argv_base[0]] + macOS font dirs (if missing)
policy:
  env:
    set: {}
    passthrough: []
  fs:
    allow_read_all: false
    allow_write_all: false
    read_paths: []
    write_paths: []
  net:
    mode: loopback
  platform:
    seatbelt:
      trace: false
```

Run composer (stdin supported):
```bash
# From the repo root
cat sandboxed_jupyter_example/composer.yaml | \
  ~/.venvs/jupyter_control/bin/python -m adgn_llm.mcp.sandboxed_jupyter_mcp.jupyter_sandbox_compose --config -
```
This writes:
- sandboxed_jupyter_example/bundle/config/jupyter_server_config.py
- sandboxed_jupyter_example/bundle/policies/policy.yaml
- sandboxed_jupyter_example/bundle/kernels/python3/kernel.json

## 2) Wire MCP to the launcher
Place this .mcp.json at the repo root, pointing to the control venv python and the generated bundle:
```json
{
  "mcpServers": {
    "sandboxed_jupyter": {
      "type": "stdio",
      "command": "~/.venvs/jupyter_control/bin/python",
      "args": [
        "-m", "adgn_llm.mcp.sandboxed_jupyter_mcp.jupyter_mcp_launch",
        "--config", "./sandboxed_jupyter_example/bundle/config",
        "--kernels", "./sandboxed_jupyter_example/bundle/kernels",
        "--workspace", "./sandboxed_jupyter_example/runtime/workspace",
        "--kernel-name", "python3",
        "--port", "0",
        "--token", "auto",
        "--start-new-runtime",
        "--log-dir", "./sandboxed_jupyter_example/runtime"
      ],
      "env": {}
    }
  }
}
```
Notes:
- The launcher starts Jupyter server and jupyter-mcp-server (stdio) using the bundle.
- The kernelspec argv runs the sandboxer (control venv python) and then your kernel argv_base inside the sandbox.

## 3) Smoke test
- Open Claude Code in this repo; it will detect .mcp.json and offer the sandboxed_jupyter MCP.
- Or launch manually by running the "command" + "args" above from a shell.
- You should see the launcher print a localhost URL and then the MCP process start.

## 4) Tighten policy over time
Start with the minimal defaults; add read_paths and write_paths explicitly as you encounter denials. Keep runtime_dir as the only default write area; add project paths only as needed.

---

## Tests: reuse this example flow
The end‑to‑end workflow tests should:
1) Create a temp repo workspace and kernel venv (install ipykernel)
2) Write a composer YAML like the one above, pointing at temporary bundle/runtime paths
3) Run the composer via the control venv’s python (stdin supported)
4) Launch jupyter-mcp-launch with the generated bundle
5) Exercise a trivial notebook (e.g., execute `print(2+2)`) via MCP

This keeps tests and docs in sync by using the same entrypoints the example prescribes.

Optional: install CLI shims globally:

````bash
uv tool install -e adgn
````
