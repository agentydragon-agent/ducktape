# MCP Architecture (Waves D-E)

This document describes the Model Context Protocol (MCP)-based architecture for agent communication and resource management, implemented in Waves D-E of the agent system redesign.

## Quick Summary

The agent runtime now uses MCP exclusively for communication between frontend/clients and backend services:

- **All communication**: HTTP/WebSocket endpoints → Single `/mcp` endpoint with Bearer token authentication
- **Subscription model**: Clients subscribe to resources, receive notifications when they change, then re-read
- **Token-based routing**: Bearer token determines destination (management server for HUMAN, compositor for AGENT)
- **Deleted infrastructure**: All WebSocket channels and HTTP REST endpoints removed

## Architecture Overview

### Components

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend UI Client                                          │
│  - Subscribes to MCP resources                             │
│  - Calls MCP tools                                          │
│  - Uses Bearer token for authentication                     │
└────────────────┬────────────────────────────────────────────┘
                 │ Bearer token
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI App with MCPRoutingMiddleware                       │
│  - Single /mcp endpoint                                    │
│  - Extracts Bearer token from Authorization header          │
│  - Routes to appropriate backend                            │
└────────────┬────────────────────────────────────────────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼ HUMAN token     ▼ AGENT token
┌───────────────┐ ┌────────────────────┐
│ Agents        │ │ Agent's Compositor │
│ Management    │ │ (for agent-1, etc.)│
│ Server        │ │                    │
│ (FastMCP)     │ │  - Policy Gateway  │
│               │ │  - Resources Srv   │
│               │ │  - Mount servers   │
└───────────────┘ └────────────────────┘
```

### Routing Architecture

The `MCPRoutingMiddleware` (in `/home/user/ducktape/adgn/src/adgn/agent/server/mcp_routing.py`) handles:

1. **Token Extraction**: Reads `Authorization: Bearer <token>` header
2. **Token Lookup**: Checks token table for role and optional `agent_id`
3. **Backend Selection**:
   - `HUMAN` tokens → Agents management server (for cross-agent operations)
   - `AGENT` tokens → Specific agent's compositor (for agent-specific MCP access)
4. **ASGI Forwarding**: Routes request to backend ASGI app
5. **Caching**: Caches backend apps by routing key for efficiency

### Token Table

Token format: `{token: {role: "human"|"agent", agent_id?: string}}`

Example:
```python
TOKEN_TABLE = {
    "human-token-123": {"role": "human"},
    "agent-token-abc": {"role": "agent", "agent_id": "agent-1"},
    "agent-token-def": {"role": "agent", "agent_id": "agent-2"},
}
```

In production, this would be replaced with database lookup or external auth service.

---

## MCP Resources

Resources are the primary data surface exposed through MCP. Clients subscribe to resources, receive notifications when they change, then re-read for latest content.

### Core Resource URIs

#### Agent Management (Management Server)

| Resource URI | Description | Subscribe | Content |
|---|---|---|---|
| `resource://agents/list` | List all agents in the system | Yes | JSON array of agent records |
| `resource://agents/{agent_id}/info` | Agent metadata (name, created_at, etc.) | Yes | Agent info object |
| `resource://agents/{agent_id}/state` | Current agent state (idle, running, suspended) | Yes | State enum + timestamp |
| `resource://agents/{agent_id}/snapshot` | Full agent snapshot (runs, approvals, MCP state) | Yes | Snapshot object |

#### Agent Session (Per-Agent Compositor)

| Resource URI | Description | Subscribe | Content |
|---|---|---|---|
| `resource://agents/{agent_id}/session/state` | Session status and connection info | Yes | Session state object |
| `resource://agents/{agent_id}/mcp/state` | Attached MCP servers and their status | Yes | Array of server mount records |
| `resource://agents/{agent_id}/ui/state` | UI messages and render state | Yes | UI state object with message history |

#### Approvals

| Resource URI | Description | Subscribe | Content |
|---|---|---|---|
| `resource://agents/{agent_id}/approvals/pending` | Pending tool call approvals for agent | Yes | Array of pending approval objects |
| `resource://agents/{agent_id}/approvals/history` | Historical approvals for agent | Yes | Array of resolved approval objects |
| `resource://approvals/pending` | All pending approvals across agents | Yes | Array of approval objects with agent_id |

#### Policy

| Resource URI | Description | Subscribe | Content |
|---|---|---|---|
| `resource://agents/{agent_id}/policy/state` | Policy state and configuration | Yes | Policy state object |
| `resource://agents/{agent_id}/policy/proposals` | Policy change proposals | Yes | Array of proposal objects |
| `resource://approval-policy/policy.py` | Active policy source code | Yes | Python policy source as text |

#### Presets & Configuration

| Resource URI | Description | Subscribe | Content |
|---|---|---|---|
| `resource://presets/list` | Available agent presets | Yes | Array of preset objects |
| `resource://container.info` | Runtime container information | Yes | Container metadata (image, Python paths, tools) |
| `resource://compositor_meta/state/{server}` | Per-server MCP mount state | Yes | Mount state (initializing, running, failed) |

---

## Subscription Pattern

### How Subscriptions Work

1. **Client subscribes**: Calls `resources/subscribe` with URI
2. **Server queues notifications**: MCP server tracks which clients are subscribed
3. **Event occurs**: Resource content changes
4. **Server broadcasts**: Calls `broadcast_resource_updated(uri)` to emit notification
5. **Client receives notification**: Gets `notifications/resources/updated` with the URI
6. **Client re-reads**: Calls `resources/read` to get latest content

### Implementation Details

#### Broadcasting Notifications

```python
# In backend code (e.g., MCP server handling tool calls)
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

server: NotifyingFastMCP = ...

# After resource state changes:
await server.broadcast_resource_updated(
    "resource://agents/agent-1/approvals/pending"
)
```

The `NotifyingFastMCP` class (in `/home/user/ducktape/adgn/src/adgn/mcp/notifying_fastmcp.py`):
- Maintains a `WeakSet[ServerSession]` of live subscriber sessions
- When `broadcast_resource_updated(uri)` is called:
  - If no sessions exist yet, queues the URI
  - When first session connects, flushes pending URIs
  - Emits `ResourceUpdatedNotification` to all active sessions
  - Handles session failures gracefully (logs and removes failed sessions)

#### Multiple Subscribers

The `WeakSet[ServerSession]` supports multiple concurrent subscribers:

```python
# Notification pattern
async def broadcast_resource_updated(self, uri: str) -> None:
    sessions = [s for s in list(self._sessions) if s is not None]
    if not sessions:
        self._pending_uris.append(uri)
        return

    # Send to all sessions concurrently
    send_tasks = [s.send_resource_updated(ANY_URL.validate_python(uri))
                  for s in sessions]
    results = await asyncio.gather(*send_tasks, return_exceptions=True)

    # Clean up failed sessions
    for s, r in zip(sessions, results, strict=False):
        if isinstance(r, Exception):
            self._sessions.discard(s)
```

### Frontend Example

```typescript
// Subscribe to pending approvals for an agent
const approvalUri = `resource://agents/${agentId}/approvals/pending`;

// 1. Subscribe
await mcpClient.subscribe(approvalUri);

// 2. Handle notifications
mcpClient.on('notification', async (notification) => {
  if (notification.params.uri === approvalUri) {
    // 3. Re-read the resource
    const result = await mcpClient.readResource(approvalUri);
    // Update UI with latest approvals
    setApprovals(result.contents);
  }
});
```

---

## Token-Based Routing

### Architecture

The `/mcp` endpoint uses a single Starlette middleware (`MCPRoutingMiddleware`) to:

1. Extract Bearer token from `Authorization` header
2. Look up token in token table to determine routing role
3. Get or create the appropriate backend ASGI app
4. Forward the HTTP request to the backend

### Token Roles

#### HUMAN Role

- **Purpose**: Cross-agent management and monitoring
- **Backend**: Agents management server (single instance)
- **Operations**:
  - List all agents
  - Monitor agent states
  - Approve/deny requests across agents
  - Manage global policies

#### AGENT Role

- **Purpose**: Agent-specific MCP access
- **Backend**: Specific agent's compositor (per-agent instance)
- **Operations**:
  - Agent reads its own session state
  - Agent calls tools in its compositor
  - Agent subscribes to its own resources

### Implementation

```python
# Token extraction
token = self._extract_bearer_token(request.scope["headers"])
# → "agent-token-abc"

# Token lookup
token_info = TOKEN_TABLE.get(token)
# → {"role": "agent", "agent_id": "agent-1"}

# Role-based backend selection
if role == TokenRole.HUMAN:
    # Use agents management server
    backend_app = self.agents_server.http_app()
elif role == TokenRole.AGENT:
    # Use specific agent's compositor
    container = await self.registry.ensure_live(agent_id)
    backend_app = container.running.compositor.http_app()

# Forward request to backend
await backend_app(request.scope, request.receive, send)
```

### Backend App Caching

Backends are cached by routing key to avoid repeated initialization:

```python
_backend_apps: dict[str, ASGIApp] = {}

backend_key = "human" if HUMAN else f"agent:{agent_id}"
if backend_key not in self._backend_apps:
    self._backend_apps[backend_key] = await self._get_backend_app(...)
return self._backend_apps[backend_key]
```

---

## Deleted Infrastructure

### WebSocket Channels (Removed)

The following WebSocket channels were used in earlier waves and have been **completely removed**:

| Channel | Path | Replaced By |
|---|---|---|
| Session channel | `/ws/session` | `resource://agents/{id}/session/state` |
| Approvals channel | `/ws/approvals` | `resource://agents/{id}/approvals/pending` |
| Policy channel | `/ws/policy` | `resource://agents/{id}/policy/state` |
| MCP servers channel | `/ws/mcp` | `resource://agents/{id}/mcp/state` |
| UI messages channel | `/ws/ui` | `resource://agents/{id}/ui/state` |
| Control channel | `/ws/control` | MCP tools (e.g., `agents_approve_request`) |

### HTTP REST Endpoints (Removed)

The following HTTP endpoints were used for agent management and have been **completely removed**:

#### Agent CRUD
- `GET /api/agents` → Use `resource://agents/list`
- `POST /api/agents` → Use MCP tool (e.g., `agents_create`)
- `GET /api/agents/{id}` → Use `resource://agents/{id}/info`
- `PUT /api/agents/{id}` → Use MCP tool (e.g., `agents_update`)
- `DELETE /api/agents/{id}` → Use MCP tool (e.g., `agents_delete`)

#### Approvals/Policy
- `GET /api/agents/{id}/approvals` → Use `resource://agents/{id}/approvals/pending`
- `POST /api/agents/{id}/approvals/{approval_id}/approve` → Use MCP tool
- `POST /api/agents/{id}/policy` → Use MCP tool

#### Miscellaneous
- `GET /health` → Kept (not MCP-based)
- `GET /static/*` → Kept (UI assets)

### Channel Bundle Infrastructure

The entire channel bundle system has been deleted:
- Channel registration and subscription tracking
- Channel-to-resource mapping tables
- Event routing to channels
- Per-channel message serialization

All functionality is now handled by:
- MCP subscription protocol (`resources/subscribe`, `resources/unsubscribe`)
- Resource notifications (`broadcast_resource_updated`)
- Direct resource reads (`resources/read`)

---

## Migration Status

### Wave D: Frontend HTTP/WebSocket Audit

- **Objective**: Identify all HTTP/WebSocket usage in frontend
- **Key findings**:
  - 9 HTTP REST endpoints identified
  - 6 WebSocket channels identified
  - 13+ MCP tools already in use
  - 6+ MCP resources already in use

### Wave E: Token-Based Routing Implementation

- **Objective**: Unified `/mcp` endpoint with role-based routing
- **Completed**:
  - Single `/mcp` endpoint via `MCPRoutingMiddleware`
  - Token extraction from Authorization header
  - HUMAN vs AGENT token routing
  - Per-agent compositor access
  - Backend app caching
  - Comprehensive test coverage

### Frontend Component Migrations

Components have been migrated from WebSocket channels to MCP subscriptions:
- **ApprovalsPanel**: `resource://agents/{id}/approvals/pending` subscription
- **ChatPane**: `resource://agents/{id}/ui/state` subscription
- **ApprovalTimeline**: `resource://agents/{id}/approvals/history` resource
- **ServersPanel**: `resource://agents/{id}/mcp/state` subscription
- **MessageComposer**: Now uses MCP prompt tools instead of HTTP endpoints
- **PresetSelector**: `resource://presets/list` resource

---

## MCP Server Organization

### Per-Agent Compositor

Each agent has a dedicated MCP compositor that:

1. **Mounts servers by prefix**:
   - `runtime_exec` → Container execution
   - `git_*` → Version control tools
   - `matrix_*` → Matrix chat integration
   - (others by project configuration)

2. **Policy middleware** enforces approvals before tool dispatch:
   - Reads active policy
   - Evaluates tool call against policy
   - Returns allow/deny decisions

3. **Resources server** provides centralized resource operations:
   - `resources/list` → Enumerate available resources
   - `resources/read` → Read resource content
   - `resources/subscribe` → Start subscription
   - `resources/unsubscribe` → Stop subscription

### Management Server

The agents management server (accessible via HUMAN tokens) provides:

1. **Cross-agent resources**:
   - `resource://agents/list` → All agents
   - `resource://agents/{id}/info` → Agent details

2. **Cross-agent tools**:
   - `agents_create` → Create new agent
   - `agents_delete` → Delete agent
   - `agents_list` → List agents (also via resource)
   - (others for agent management)

---

## Error Handling

### MCP Errors

Errors are returned as MCP protocol errors with structured details:

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32950,
    "message": "policy_denied",
    "data": {
      "type": "policy_denied",
      "decision": "deny_abort",
      "reason": "Tool execution not permitted by policy"
    }
  },
  "id": 42
}
```

### Authorization Errors

Token-related errors are returned by the routing middleware:

```
401: Missing Authorization header
401: Invalid token
500: Routing error (malformed token info, agent not found, etc.)
```

---

## Security Considerations

### Authentication

- All clients must provide a valid Bearer token
- Tokens are validated against the token table
- Missing or invalid tokens result in 401 Unauthorized

### Authorization

- Token role determines which backend is accessible
- HUMAN tokens cannot call AGENT-specific operations
- Policy middleware enforces fine-grained operation approval

### Token Management

- Tokens are currently stored in-memory (suitable for development)
- Production deployments should:
  - Move token table to secure database
  - Implement token rotation
  - Add expiration timestamps
  - Use external auth service (OIDC, etc.)

---

## Performance Considerations

### Subscription Efficiency

- `WeakSet[ServerSession]` automatically removes sessions when garbage collected
- Failed notification sends are logged but don't block other subscribers
- No coalescing or deduplication at this layer (application responsibility)

### Backend Caching

- Compositor apps are cached by routing key
- Avoids repeated HTTP app initialization
- Cache is per-middleware instance (shared across requests)

### Concurrent Notifications

- Broadcasting uses `asyncio.gather()` for concurrent sends
- Failures in one session don't affect others
- Timeouts are handled by application-level timeouts

---

## Future Enhancements

1. **Token Database**: Move from in-memory token table to persistent storage
2. **Token Rotation**: Implement automatic token expiration and rotation
3. **Per-Session Subscriptions**: Track subscriptions per session for efficient cleanup
4. **Resource Caching**: Optional client-side caching with CRC validation
5. **Batched Notifications**: Coalesce multiple resource updates into single notifications
6. **Rate Limiting**: Per-token rate limiting on subscription/unsubscription

---

## References

- `src/adgn/agent/server/mcp_routing.py` - Routing middleware implementation
- `src/adgn/mcp/notifying_fastmcp.py` - Notification broadcasting
- `src/adgn/agent/server/app.py` - FastAPI integration
- `docs/mcp-runtime/` - Additional MCP runtime documentation
- `docs/mcp-runtime/resources.md` - Resources server details
- `docs/mcp-runtime/overview.md` - Full runtime architecture
