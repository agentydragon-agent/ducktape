# STDIO Server Mode

Purpose: provide a single-command entry point suitable for MCP clients that expect a stdio MCP server, with minimal configuration. In this mode:

- `workspace` defaults to current working directory (repo root recommended)
- `document-id` is auto-created under `.mcp/scratch/...ipynb`
- Kernel sandbox is ON by default; Jupyter server runs unsandboxed; writes allowed under WORKSPACE, RUN_ROOT, /tmp
- Transport: stdio; provider: jupyter

## Usage

```bash
sandbox-jupyter-mcp --stdio-server
```

Options like `--trace-sandbox` and `--jupyter-port` still apply. Example:

```bash
sandbox-jupyter-mcp --stdio-server --trace-sandbox --jupyter-port 0
```

Behavior:
- Picks a free port if `--jupyter-port 0` (default)
- Auto-creates a new notebook in WORKSPACE/.mcp/scratch
- Prints MCP stdio responses to stdout; logs are written under RUN_ROOT

Recommended: run from repo root so WORKSPACE matches your project and writes are permitted anywhere under it.
