# MCP Runtime Documentation

This directory contains comprehensive documentation for the Model Context Protocol (MCP) based runtime architecture, covering both frontend communication and internal implementation details.

## Quick Navigation

### Frontend & Client Communication

**Start here**: `@../mcp-architecture.md`
- Token-based routing via single `/mcp` endpoint
- MCP resources (subscription model)
- Notification broadcasting pattern
- Deleted WebSocket/HTTP endpoints
- Security & token management

### Internal Runtime Architecture

**Start here**: `@overview.md`
- Internal design of V1 sync execution
- Agent/Compositor/Resources server organization
- Turn orchestration and policy enforcement
- Container-initiated calls and async signaling

### Detailed Components

| Document | Purpose |
|---|---|
| `resources.md` | Resources server implementation and API |
| `policy-gateway.md` | Policy middleware and approval enforcement |
| `control.md` | Loop control and turn yielding |
| `ui-chat.md` | UI chat resource mode (MCP-based messaging) |
| `matrix.md` | Matrix chat server integration |

## Architecture Overview

```
┌─────────────────────────────────────────┐
│         Frontend UI Clients              │
│  (HTTP/WebSocket replaced with /mcp)    │
└────────────────┬────────────────────────┘
                 │ Bearer token
                 ▼
        ┌────────────────┐
        │  /mcp endpoint │  ← Token-based routing
        │   middleware   │     (see mcp-architecture.md)
        └────────┬───────┘
                 │
    ┌────────────┴────────────┐
    │                         │
    ▼ HUMAN token       ▼ AGENT token
┌──────────────┐   ┌─────────────────────┐
│ Management   │   │ Agent Compositor    │
│ Server       │   │  ┌───────────────┐ │
│              │   │  │ Policy Gateway│ │
└──────────────┘   │  ├───────────────┤ │
                   │  │Resources Srv  │ │
                   │  ├───────────────┤ │
                   │  │Mounted Servers│ │
                   │  └───────────────┘ │
                   └─────────────────────┘

Internal Runtime (see overview.md):
┌─────────────────────────────────────┐
│  Agent (MiniCodex)                  │
│  - Runs turns synchronously         │
│  - Tool calls gated by policy       │
│  - Results fed back to model        │
└────────────┬────────────────────────┘
             │
       ┌─────▼─────┐
       │ Compositor│
       │ + Policy  │
       │ Middleware│
       └───────────┘
```

## Key Concepts

### MCP Resources

Resources are first-class data exposed via MCP protocol:
- Clients **subscribe** to resources
- Server broadcasts **notification** when resource changes
- Clients **re-read** to get latest content
- See `@../mcp-architecture.md` for resource URIs and examples

### Token-Based Routing

Single `/mcp` endpoint with Bearer token authentication:
- **HUMAN tokens** → Management server (cross-agent operations)
- **AGENT tokens** → Per-agent compositor (agent-specific access)
- See `@../mcp-architecture.md` for token format and implementation

### Subscription Pattern

Implemented via `NotifyingFastMCP`:
- `broadcast_resource_updated(uri)` to emit notifications
- `WeakSet[ServerSession]` tracks subscriber sessions
- Multiple subscribers supported per resource
- See `@../mcp-architecture.md` for code examples

## Wave D-E Summary

### Wave D: Frontend HTTP Audit
- Identified all HTTP/WebSocket usage in frontend
- Found 9 HTTP REST endpoints and 6 WebSocket channels
- Planned migration to MCP resources and subscriptions

### Wave E: Token-Based Routing
- Implemented single `/mcp` endpoint
- Added Bearer token authentication
- Role-based routing (HUMAN/AGENT)
- Deleted all legacy HTTP/WebSocket endpoints

### Result
- All frontend communication now uses MCP
- Resources replace WebSocket channels
- Tools replace REST endpoints
- Cleaner, more consistent protocol surface

## Common Tasks

### Adding a New Resource

1. Define resource URI (e.g., `resource://agents/{id}/new-state`)
2. Implement resource handler in appropriate server
3. Emit notification via `await server.broadcast_resource_updated(uri)`
4. Document in `@../mcp-architecture.md` resources table
5. Frontend subscribes to resource URI

### Adding a New MCP Tool

1. Define Pydantic input/output models
2. Implement tool method with `@server.tool()` decorator
3. Register in compositor or per-agent server
4. Tool is automatically listed via `resources/list` and mounted under prefix
5. Policy middleware enforces approvals on tool calls

### Debugging MCP Issues

1. Check token in Authorization header
2. Verify token exists in `TOKEN_TABLE` (see `mcp_routing.py`)
3. Check bearer token syntax: `Authorization: Bearer <token>`
4. Verify backend app is correctly routed based on token role
5. Check subscription receipts and re-read operations in client

## Testing

Tests for MCP routing, subscriptions, and resources:
- `tests/agent/server/test_mcp_routing.py` - Routing middleware tests
- `tests/agent/e2e/` - End-to-end MCP tests
- Run with: `pytest tests/agent/server/ -q`

## References

- MCP Specification: https://modelcontextprotocol.io/
- FastMCP Documentation: https://gofastmcp.com/
- Starlette Documentation: https://www.starlette.io/
- FastAPI Documentation: https://fastapi.tiangolo.com/
