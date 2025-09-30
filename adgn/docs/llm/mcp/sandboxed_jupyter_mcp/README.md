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

## Quick reproducer

Use the standalone script to reproduce a seatbelt-wrapped Jupyter + MCP session without pytest:

```bash
/Users/mpokorny/code/ducktape/adgn/src/adgn/mcp/sandboxed_jupyter_mcp/run_one.sh \
  /abs/path/to/.sandbox_jupyter.yaml \
  /abs/workspace \
  /abs/run_root \
  --port 0
```

The script:
- Creates expected runtime dirs under RUN_ROOT (runtime, data, config, mpl, pycache, tmp)
- Sets SJ_DEBUG_DIAG=1 for verbose diagnostics
- Points SJ_POLICY_ECHO_DIR at RUN_ROOT/tmp so the composed seatbelt policy and -D defs are captured
- Enables JUPYTER_PLATFORM_DIRS=1
- Launches the wrapper in seatbelt mode with sandbox tracing enabled

Logs:
- Jupyter: RUN_ROOT/runtime/jupyter_server.{out,err}
- Sandbox policy echo: RUN_ROOT/tmp/policy.sb and policy_defs.json
- Seatbelt trace: RUN_ROOT/tmp/seatbelt.trace.log (if tracing enabled)

## Observability toggles

- SJ_DEBUG_DIAG=1: enable verbose diagnostics and force sandboxer --debug
- SJ_POLICY_ECHO_DIR=/path: write composed policy.sb and policy_defs.json to /path
- JUPYTER_PLATFORM_DIRS=1: opt into platformdirs-based paths (reduces warnings)

## Example setup (see sandboxed_jupyter_example/)

For a complete per-repo setup, including directory layout, explicit policy.yaml examples, and .mcp.json wiring, see:

- sandboxed_jupyter_example/README.md

Below are minimal inline templates if you prefer to copy/paste here.

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

## Example policy schema (explicit)

See sandboxed_jupyter_example/README.md for full examples.
- allow_read_all: bool
- allow_write_all: bool
- read_paths: list[str]
- write_paths: list[str]
- env: dict[str,str]
- env_passthrough: list[str]

## Semantics

- WORKSPACE: absolute path to repo/workspace root; kernel may read/write anywhere under this path
- RUN_ROOT: sandbox runtime dir created under run_root (logs, kernelspec, Jupyter state)
- Jupyter server runs unsandboxed; kernel process sandboxed via custom kernelspec when seatbelt is active
- Network: loopback Jupyter; policy controls kernel networking

## Manual Testing (tmux)

For an end-to-end manual workflow, see docs/TMUX_MANUAL_TESTING.md. It walks through launching the wrapper, inspecting logs, and sending MCP requests over stdio.

## Tests

Pytest fixtures provide a DRY harness (see tests/conftest.py). Run:
```bash
pytest -q adgn/src/adgn/mcp/sandboxed_jupyter_mcp/tests/
```
