# Specimen: ducktape adgn agent (2025-11-20)

## Purpose

This specimen captures code quality findings in the adgn agent codebase, focusing on type correctness and defensive programming anti-patterns.

## Key Findings

### Issue 001: Normalization function for type that cannot occur

**Function**: `_normalize_call_arguments` in `adgn/src/adgn/agent/agent.py:149-160`

This function accepts `dict[str, Any] | str | None` but is only ever called with `str | None` (from `FunctionCallItem.arguments`). The defensive `json.dumps()` fallback is unreachable because all construction paths guarantee string format.

**Key insight**: There should never be a code path where one doesn't know whether they hold a JSON dict, a string, or None. A caller should always be reduced to *either* a `json.dumps()` *or* identity operation, never both in a runtime type check.

**Properties violated**:
- `type-correctness-and-specificity`: Type signature is too wide (includes `dict[str, Any]` which never occurs)
- `no-dead-code`: The `json.dumps()` branch is unreachable
- `truthfulness`: Function contract suggests ambiguity that doesn't exist in practice

### Issue 002: Unused --ui-port flag misleads users

**Flag**: `--ui-port` in `adgn/src/adgn/agent/mcp_bridge/cli.py:63`

The `--ui-port` flag is defined with help text promising "Management UI port (WebSocket channels, no token auth)", but:
- In single-agent mode: completely unused (no UI app created)
- In multi-agent mode: binds a stub FastAPI app with unimplemented WebSocket (`/ws/mcp` returns "not_implemented")
- No web frontend exists (no HTML/JS/Svelte files)
- Log messages mislead users: "Management UI: http://{host}:{ui_port}" and "MCP: ws://{host}:{ui_port}/ws/mcp"

The flag's only functional use is binding uvicorn to a port that serves stubs and proxies. This creates false expectations and unnecessary complexity.

**Properties violated**:
- `no-dead-code`: Flag serves no real purpose (stub functionality only)
- `truthfulness`: CLI help and logs mislead about Management UI existence
- `least-power`: Creates unnecessary separation (two ports) when one would suffice

### Issue 003: Silent failure when config file doesn't exist

**Code**: File existence check in `adgn/src/adgn/agent/mcp_bridge/cli.py:86-89`

When user provides `--mcp-config` path to a non-existent file, the code silently falls back to empty config without error or notification:
```python
if mcp_config and mcp_config.exists():
    config = MCPConfig.model_validate_json(mcp_config.read_text())
else:
    config = MCPConfig(mcpServers={})  # Silent fallback
```

**Problem**: User explicitly specified a config file (not optional/auto-detected). Non-existence likely indicates typo, wrong directory, or deleted file. Silent fallback masks the error - server starts successfully, user discovers later that servers are missing.

**Correct behavior** (per user guidance):
- Option 1: Remove `exists()` check, let `FileNotFoundError` propagate naturally (fail fast)
- Option 2: Explicitly report error: `raise click.UsageError(f"MCP config file not found: {mcp_config}")`

Same pattern exists for `--initial-policy` flag (lines 92-93).

**Properties violated**:
- `truthfulness`: Silent failure masks error from user
- `no-swallowing-errors`: Error condition ignored without notification
- `least-power`: Defensive check adds complexity without benefit

## Scope

Focus on the adgn agent core (`adgn/src/adgn/agent/`), particularly:
- Type correctness in data flow
- Defensive programming that contradicts type system
- Functions that should not exist due to type guarantees
