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
