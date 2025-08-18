# TODO: Worktree-level service idea

Concept: run sandboxed Jupyter MCP servers as a per-worktree background service managed by `wt`.

Sketch:
- `wt` allocates a JP_PORT and per-worktree JUPYTER_* dirs under `.wt/state/jupyter/`
- Starts `sandbox-jupyter-mcp --workspace <root> --mode seatbelt --jupyter-port $PORT` with inherited env
- Exposes an mcpServers block or a small shim to register with clients
- Lifecycle: `wt up` / `wt down` manage the server

Not implemented yet. Keep wrapper minimal for now.
