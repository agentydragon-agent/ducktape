# sandbox-jupyter-mcp

A small wrapper that launches a Jupyter Server and an MCP stdio server with optional sandboxing.
- macOS seatbelt (default) with kernel-only sandbox
- Docker mode (optional)
- Newline-delimited JSON over stdio (MCP protocol)

## Quick Start (STDIO server mode)

Use this to embed directly in an MCP client expecting a stdio server. Workspace defaults to cwd and a scratch notebook is created automatically.

```bash
sandbox-jupyter-mcp --stdio-server
```

Options still work (e.g., pick port, trace sandbox):
```bash
sandbox-jupyter-mcp --stdio-server --trace-sandbox --jupyter-port 0
```

## Typical Wrapper Usage

Seatbelt (kernel sandbox on):
```bash
sandbox-jupyter-mcp \
  --workspace /abs/repo/root \
  --mode seatbelt \
  --jupyter-port 0 \
  --start-new-runtime
```

Kernel unsandboxed (for debugging):
```bash
sandbox-jupyter-mcp \
  --workspace /abs/repo/root \
  --mode seatbelt \
  --jupyter-port 0 \
  --no-kernel-sandbox
```

Docker mode (containerized Jupyter+MCP):
```bash
sandbox-jupyter-mcp \
  --workspace /abs/repo/root \
  --mode docker \
  --docker-image python:3.12-slim \
  --jupyter-port 18888 \
  --start-new-runtime
```

## Semantics

- WORKSPACE: absolute path to repo/workspace root; kernel may read/write anywhere under this path
- RUN_ROOT: ephemeral per-run dir under /tmp (runtime logs, kernelspec, Jupyter state)
- Jupyter server runs unsandboxed; kernel process sandboxed via custom kernelspec when seatbelt is active
- Network: loopback Jupyter; current policy is permissive; see TODOs to tighten

## Manual Testing (tmux)

See docs/TMUX_MANUAL_TESTING.md for a full manual workflow and helper scripts in scripts/.

## Roadmap / TODOs

- Tighten seatbelt policy while keeping tests green
- Expand test coverage (multi-call, error paths)

## Tests

Pytest fixtures provide a DRY harness (see tests/conftest.py). Run:
```bash
pytest -q llm/mcp/jupyter_mcp_stdio_guard/tests/
```
