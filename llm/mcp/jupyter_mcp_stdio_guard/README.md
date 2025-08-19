# sandbox-jupyter-mcp

A small wrapper that launches a Jupyter Server and an MCP stdio server with optional sandboxing.
- macOS seatbelt (default) with kernel-only sandbox
- Docker mode (optional)
- Newline-delimited JSON over stdio (MCP protocol)

## CLI

We now use subcommands. The primary command is stdio and an explicit policy config is required.

```bash
sandbox-jupyter-mcp stdio --policy-config /abs/worktree/.sandbox_jupyter.yaml
```

Use --trace-sandbox, --no-kernel-sandbox, --jupyter-port as needed.

## Example .mcp.json (genericized)

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "sandbox-jupyter-mcp",
      "args": [
        "stdio",
        "--policy-config=/abs/worktree/.sandbox_jupyter.yaml"
      ],
      "env": {}
    }
  }
}
```

## Example .sandbox_jupyter.yaml (template)

```yaml
workspace: /abs/worktree/.sandbox_workspace
run_root: /abs/worktree/.sandbox_run
net: loopback
env:
  PATH: /abs/venv/bin:$PATH
  LANG: en_US.UTF-8
  PYTHONPATH: ""
  VIRTUAL_ENV: /abs/venv
  JUPYTER_RUNTIME_DIR: /abs/worktree/.sandbox_run/runtime
  JUPYTER_DATA_DIR: /abs/worktree/.sandbox_run/data
  JUPYTER_CONFIG_DIR: /abs/worktree/.sandbox_run/config
  JUPYTER_PATH: /abs/worktree/.sandbox_run/data
  MPLCONFIGDIR: /abs/worktree/.sandbox_run/mpl
  PYTHONPYCACHEPREFIX: /abs/worktree/.sandbox_run/pycache
  TMPDIR: /abs/worktree/.sandbox_run/tmp
  TMP: /abs/worktree/.sandbox_run/tmp
  TEMP: /abs/worktree/.sandbox_run/tmp
  HOME: /abs/worktree/.sandbox_run/
  PYTHONUNBUFFERED: "1"
fs_read:
- /abs/worktree
- /abs/venv
fs_write:
- /abs/worktree/.sandbox_workspace
- /abs/worktree/.sandbox_run
```

## Semantics

- WORKSPACE: absolute path to repo/workspace root; kernel may read/write anywhere under this path
- RUN_ROOT: sandbox runtime dir created under run_root (logs, kernelspec, Jupyter state)
- Jupyter server runs unsandboxed; kernel process sandboxed via custom kernelspec when seatbelt is active
- Network: loopback Jupyter; current policy is permissive; see TODOs to tighten

## Manual Testing (tmux)

For an end-to-end manual workflow, see docs/TMUX_MANUAL_TESTING.md. It walks through launching the wrapper, inspecting logs, and sending MCP requests over stdio.

## TODOs

- Network sandbox enforcement: net policy is not enforced yet; current policy allows outbound by default. Tighten once kernel/runtime networking strategy is finalized.
- Policy hardening iteratively (file system read/write allowlists) while keeping tests green.

## Tests

Pytest fixtures provide a DRY harness (see tests/conftest.py). Run:
```bash
pytest -q llm/mcp/jupyter_mcp_stdio_guard/tests/
```
