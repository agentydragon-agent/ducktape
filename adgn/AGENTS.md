@README.md

# Agent Guide for `adgn`

This file provides agent-specific conventions and prescriptions for working on the `adgn` package.

## Properties/specimens

**For detailed props-specific documentation, see:**

- @src/adgn/props/AGENTS.md — Complete guide to specimens, models, database, tooling, and workflows
- @src/adgn/props/CLAUDE.md — Props package conventions and authoring
- Quick start: `props run --snapshot <slug>` or `props snapshot exec <snapshot-slug>`

### Testing LLM Code

- Typical: `direnv exec adgn pytest -q -m "not live_llm"`
- Excluding a suite: `-k "not sandboxed_jupyter"`
- `live_llm` tests require API keys and network access

## Bootstrap Handlers (Agent Initialization)

Bootstrap handlers inject synthetic function calls before the agent's first sampling cycle,
providing initial context without requiring explicit agent requests.

**Pattern (immediate construction):**

```python
from adgn.agent.bootstrap import TypedBootstrapBuilder, BootstrapHandler, docker_exec_call, read_package_file_call

# Create builder with introspection (validates payload types against server schema)
builder = TypedBootstrapBuilder.for_server(runtime_server)

# Create handler. Build calls immediately - no factories, no inheritance
bootstrap = BootstrapHandler([
    # Standalone helper functions:
    docker_exec_call(builder, server=runtime, cmd=["ls", "-la"]),
    read_package_file_call(builder, server=runtime, path="pyproject.toml"),
    # Method on builder for resource reads:
    builder.read_resource(comp.resources, server=some_mount, uri="resource://foo/bar"),
])
handlers = [bootstrap, ...other handlers...]
```

**Key principles:**

- Builder instances are local (no global state)
- Auto-generates call_ids (no manual management needed)
- Type-safe: Pydantic payloads validated via introspection
- Immediate construction (not factories/lambdas)
- Standalone helper: `docker_exec_call()`
- Builder method: `builder.read_resource()` for resources server reads

**Future enhancement:** See `src/adgn/agent/docs/bootstrap_type_safety.md` for plans to eliminate
string literals via generic/typed stubs

## Conventions and Tips

- MCP naming
  - When composing MCP tool names programmatically, use `build_mcp_function(server, tool)` from `mcp_infra.naming`.
  - Avoid hard-coded strings like `server_tool` in code. Literal forms in docs/examples are illustrative only.
- FastMCP error handling
  - Do not wrap tool bodies in broad try/except. Uncaught exceptions become MCP errors (`isError=true`) with messages.
  - Prefer Pydantic models for inputs/outputs; validation errors surface as MCP errors automatically.
- Arg0 virtual CLIs
  - Virtual commands are exposed by argv0 name on PATH, e.g., `apply_patch` (`applypatch` alias)
    to apply OpenAI‑style patch envelopes
  - Symlink creation is strict; failures abort startup
- MCP CallToolResult handling
  - FastMCP client returns `fastmcp.client.client.CallToolResult` (snake_case fields: `is_error`,
    `structured_content`). MCP Pydantic uses `mcp.types.CallToolResult` (camelCase aliases:
    `isError`, `structuredContent`). Use the appropriate type at each layer.
- Typing discipline
  - Handle exact runtime types. When an external API returns a loose object, convert it at the
    boundary so the rest of the code sees a single concrete type.
  - Centralize boundary conversions (e.g., `_normalize_result`/`_call_structured`) instead of
    duplicating `isinstance` + conversion logic.
- MCP servers with agent‑specific state
  - Prefer constructors that accept per‑agent state (no hidden globals/singletons)
  - In‑proc servers are mounted on a `Compositor` (via `mount_inproc(...)`)

### MCP Conventions

See `mcp_infra/AGENTS.md` for compositor, resources, and subscriptions conventions.

### CallToolResult Conventions (MCP)

- FastMCP client returns a lightweight `CallToolResult` dataclass (not a Pydantic model) with
  snake_case fields (`is_error`, `structured_content`).
- Pydantic MCP types live under `mcp.types` (e.g., `mcp.types.CallToolResult`) with camelCase
  aliases (`isError`, `structuredContent`). Use these when you need typed validation/serialization.
- Convert between types at boundaries as needed. For simple cases, construct
  `mcp.types.CallToolResult(content=..., structuredContent=..., isError=...)` directly.
- Do not call `.model_dump()` on FastMCP's client `CallToolResult` — it isn't a Pydantic model.

## Notes and Caveats

- Tests marked `real_github` or `live_llm` talk to network/services; run explicitly

## References and Further Reading

- Bootstrap type safety: `src/adgn/agent/docs/bootstrap_type_safety.md`
- Approval policy implementation: `src/adgn/agent/approvals.py`
- Agent presets: see README.md "Agent Presets" (if available)

@instructions/fastmcp_pydantic.md
@instructions/fastmcp_exceptions.md
