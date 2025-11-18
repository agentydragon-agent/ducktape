# MCP-Based Management UI Plan

## Executive Summary

Replace custom WebSocket channels with MCP protocol for the Management UI. The frontend will be an MCP client connecting to multiple independent MCP servers via Streamable HTTP. This provides a clean security boundary, reuses MCP infrastructure, and enables future features like elicitations for approvals.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     Frontend (Browser)                       │
│  - Multiple MCP clients (Streamable HTTP)                   │
│  - Token in URL → localStorage                              │
│  - Clients:                                                  │
│    • agents (cross-agent management)                        │
│    • state_{agent_id} (per local agent)                     │
│    • approvals_{agent_id} (per agent)                       │
│    • compositor_meta_{agent_id} (per agent)                 │
└──────────────┬───────────────────────────────────────────────┘
               │ HTTP GET /ui?token=...
               │ Streamable HTTP to MCP endpoints
               ▼
┌──────────────────────────────────────────────────────────────┐
│           Management UI Server (Port 8081)                   │
│  - Serves static files + token auth                         │
│  - Path-based routing to MCP servers:                       │
│    GET /mcp/agents → agents server                          │
│    GET /mcp/{id}/state → state server (local only)          │
│    GET /mcp/{id}/approvals → approval server                │
│    GET /mcp/{id}/compositor → compositor_meta server        │
└──────────────▲───────────────────────────────────────────────┘
               │ InfrastructureRegistry
               │ (per-agent infrastructure)
               │
┌──────────────────────────────────────────────────────────────┐
│              MCP Server (Port 8080)                          │
│  - Token-authenticated MCP-over-HTTP                        │
│  - Routes to per-agent compositor                           │
│  - For external agents (ChatGPT, Claude Desktop, etc.)      │
└──────────────────────────────────────────────────────────────┘
```

## Key Decisions to Make

### 1. Architecture: Multiple Servers vs. Single Compositor

**Option A: Multiple Independent MCP Servers** (RECOMMENDED)
- ✅ Each server has specific purpose with bespoke UI rendering
- ✅ Clean separation of concerns
- ✅ Matches existing pattern (approval_policy split into reader/proposer/approver)
- ✅ Easier to understand security boundaries
- ✅ Frontend can handle each server type differently
- ❌ More connections to manage

**Option B: Single Meta Compositor**
- ✅ Single connection for all admin operations
- ✅ Can dynamically advertise capabilities (local vs bridge mode)
- ❌ Mixed concerns in one server
- ❌ Less clear security model

**Decision**: **Option C** - Multiple independent servers PLUS a cross-agent management server.
- **`agents` server**: Global server listing all agents and their states
- **Per-agent servers**: `approvals_{agent_id}`, `compositor_meta_{agent_id}`, etc.
- Clean separation of concerns with discoverability via meta-server

### 2. Per-Agent Routing

**Decision**: Path-based routing with dedicated endpoints per server.

**Routes**:
```
/mcp/agents                   → Cross-agent management (lists all agents + states)
/mcp/{agent_id}/approvals     → Per-agent approval server
/mcp/{agent_id}/compositor    → Per-agent MCP server list (compositor_meta)
/mcp/{agent_id}/state         → Per-agent sampling state (for local agents)
```

More RESTful, clearer routing logic, easier to debug.

### 3. Authentication & Security

**Requirements**:
- Management UI must be token-protected (only human can access)
- Token auto-generated on boot, printed to CLI
- Token passed via URL query param, auto-inserted by frontend
- Secure against unauthorized access

**Implementation**:
```python
# On server boot:
ui_token = secrets.token_urlsafe(32)
print(f"Management UI: http://localhost:8081/ui?token={ui_token}")

# Frontend receives token from URL:
const params = new URLSearchParams(window.location.search)
const uiToken = params.get('token')

# All MCP requests include token:
headers: { 'Authorization': `Bearer ${uiToken}` }
```

**Decision**:
- **Session-based** token (valid for server lifetime)
- **Generate new token on each boot** (or allow env var override for configured secret)
- **Store in localStorage** for convenience (optional, graceful fallback if auth fails)
- **No expiry** during server lifetime

### 4. MCP Elicitations for Approvals

MCP elicitations are **perfect** for approval flows:

**Standard Approval Flow (Current)**:
1. Tool call blocked by policy
2. Approval request sent to UI via WebSocket
3. UI shows approval dialog
4. User approves/denies
5. Result sent back, tool call proceeds/fails

**Elicitation-Based Flow (Future)**:
1. Tool call blocked by policy
2. Agent requests elicitation with approval details
3. MCP client (UI) shows native approval dialog
4. User accepts/declines/cancels (3-action model)
5. Response includes approval decision

**Benefits**:
- Standardized human-in-the-loop workflow
- Three-action model (accept/decline/cancel) built-in
- Clients control UX (no server-dictated UI)
- Security: server can't request PII/credentials

**Decision**:
- **Phase in later** (after basic MCP migration works - Phase 5+)
- **Keep current approval engine**, add elicitation layer on top when ready
- This allows us to prove out the MCP architecture first before adding elicitations

### 5. Shared Pydantic/TypeScript Models (SSOT)

**Problem**: Duplicate type definitions between Python (Pydantic) and TypeScript

**Options**:

**Option A: Generate TypeScript from Pydantic**
- Use `pydantic-to-typescript` or similar
- Python is SSOT
- Automated generation in build step

**Option B: Generate Pydantic from TypeScript**
- TypeScript is SSOT
- Less common tooling

**Option C: Shared JSON Schema**
- Both Python and TypeScript generate from JSON Schema
- Most flexible but more complex

**Option D: Manual maintenance with validation tests**
- Write types in both languages
- Runtime validation tests ensure compatibility

**Decision**: **Auto-generate TypeScript from Pydantic** (Python is SSOT).

**Scope**: All models that define MCP inputs/outputs that the frontend uses:
- `ApprovalBrief`, `ApprovalPendingEvt`
- `ServerCapabilities`
- `SamplingSnapshot`, `ServerEntry` (discriminated union)
- Policy models (`PolicyRequest`, `PolicyResponse`)
- Any other MCP resource/tool schemas

**Implementation**:
```bash
# Add to package.json
"scripts": {
  "generate-types": "pydantic2ts --module adgn.agent.server.protocol --output src/types/protocol.ts"
}
```

## Implementation Plan

### Phase 1: Backend - Independent MCP Servers

**1.1 Cross-Agent Management Server** (`agents`)

Exposes list of all known agents with their capabilities and states.

```python
# adgn/src/adgn/agent/mcp_bridge/servers/agents.py

from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

def make_agents_server(registry: InfrastructureRegistry) -> NotifyingFastMCP:
    """Cross-agent management: list all agents and their states."""
    server = NotifyingFastMCP(
        name="agents",
        instructions="Cross-agent management metadata."
    )

    @server.resource(
        "resource://agents/list",
        name="agents.list",
        mime_type="application/json"
    )
    async def list_agents():
        """List all known agents with capabilities and state."""
        agents = []
        for agent_id in registry.known_agents():
            infra, _ = await registry.get_or_create_infrastructure(agent_id)

            # Detect agent type based on two factors:
            # (a) Has chat/UI component
            # (b) Agent loop is under our control
            has_chat = hasattr(infra, 'chat_component') and infra.chat_component is not None
            has_agent_loop = hasattr(infra, 'agent_loop') and infra.agent_loop is not None

            agent_info = {
                "agent_id": agent_id,
                "capabilities": {
                    "chat": has_chat,
                    "agent_loop": has_agent_loop,
                },
                "mode": "local" if has_agent_loop else "bridge",
            }

            # Only local agents have sampling state available
            # (we have no way to know external agents' sampling states)
            if has_agent_loop:
                # Link to per-agent state resource
                agent_info["state_uri"] = f"resource://{agent_id}/state"

            agents.append(agent_info)
        return agents

    return server
```

**Notes**:
- Agent mode detection considers both chat component and agent loop control
- External agents (bridge mode) have no sampling state
- Sampling state accessed via per-agent `/mcp/{agent_id}/state` endpoint

**1.2 Per-Agent Approval Server** (`approvals_{agent_id}`)

Reuse existing `ApprovalPolicyServer` with minor modifications:

```python
# Mount per-agent approval servers
async def mount_approval_server_for_agent(app: FastAPI, agent_id: str, registry: InfrastructureRegistry):
    """Mount approval server at /mcp/{agent_id}/approvals"""
    infra, _ = await registry.get_or_create_infrastructure(agent_id)

    # Reuse existing ApprovalPolicyServer
    approval_server = ApprovalPolicyServer(infra.approval_engine, name=f"approvals_{agent_id}")

    # Serve via Streamable HTTP at dedicated path
    # TODO: Implement path-based routing middleware
```

**1.3 Per-Agent Compositor Meta Server** (`compositor_meta_{agent_id}`)

Reuse existing `compositor_meta` server pattern:

```python
# Already exists! Just mount per-agent:
infra, _ = await registry.get_or_create_infrastructure(agent_id)
meta_server = make_compositor_meta_server(compositor=infra.compositor, name=f"compositor_meta_{agent_id}")
```

**1.4 Per-Agent State Server** (`state_{agent_id}`)

Expose sampling state for local agents (agents where we control the loop).

```python
# adgn/src/adgn/agent/mcp_bridge/servers/state.py

from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

def make_state_server(agent_id: str, registry: InfrastructureRegistry) -> NotifyingFastMCP:
    """Expose sampling state for a local agent."""
    server = NotifyingFastMCP(
        name=f"state_{agent_id}",
        instructions=f"Sampling state for agent {agent_id}."
    )

    @server.resource(
        f"resource://{agent_id}/state",
        name="sampling.state",
        mime_type="application/json"
    )
    async def get_sampling_state():
        """Get current sampling state."""
        infra, _ = await registry.get_or_create_infrastructure(agent_id)

        # Only available for local agents with agent loop
        if not hasattr(infra, 'agent_loop') or infra.agent_loop is None:
            raise ValueError(f"Agent {agent_id} has no agent loop")

        # Return sampling snapshot (matches existing WebSocket format)
        return await infra.compositor.sampling_snapshot()

    # Listen to agent state changes and broadcast updates
    # (Hook into agent loop state machine transitions)

    return server
```

**Notes**:
- Only available for local agents (where we control the agent loop)
- External agents (bridge mode) get 404 on this endpoint
- Resource notifications broadcast when agent state changes (idle ↔ running)

**1.5 Token Authentication Middleware**

```python
# adgn/src/adgn/agent/mcp_bridge/server.py

class UITokenAuthMiddleware:
    """Validates UI token from Authorization header."""

    def __init__(self, app, ui_token: str):
        self.app = app
        self.ui_token = ui_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Extract token from Authorization header
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode()

        if not auth.startswith("Bearer "):
            return await send_401(send)

        token = auth[7:]  # Remove "Bearer "
        if token != self.ui_token:
            return await send_401(send)

        # Token valid, proceed
        await self.app(scope, receive, send)
```

**1.6 Path-Based Routing to MCP Servers**

```python
# Route requests to correct MCP server based on path

@app.get("/mcp/agents")
async def agents_endpoint():
    # Serve cross-agent management server via Streamable HTTP
    pass

@app.get("/mcp/{agent_id}/approvals")
async def approval_endpoint(agent_id: str):
    # Serve approval server for agent_id
    pass

@app.get("/mcp/{agent_id}/compositor")
async def compositor_endpoint(agent_id: str):
    # Serve compositor_meta server for agent_id
    pass

@app.get("/mcp/{agent_id}/state")
async def state_endpoint(agent_id: str):
    # Serve sampling state server for agent_id (local agents only)
    # Returns 404 for bridge mode agents
    pass
```

**Implementation Approach**:
- Use `fastmcp.server.run_streamable_http` per-server
- FastAPI sub-apps mounted at different paths for clean routing

### Phase 2: Frontend - MCP Client

**2.1 Install SDK**

```bash
cd src/adgn/agent/web
npm install @modelcontextprotocol/sdk
```

**2.2 Create MCP Client Utilities**

```typescript
// src/features/mcp/client.ts

import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'

export interface MCPClientConfig {
  name: string
  url: string
  token: string
}

export async function createMCPClient(config: MCPClientConfig): Promise<Client> {
  const transport = new StreamableHTTPClientTransport({
    url: config.url,
    headers: {
      'Authorization': `Bearer ${config.token}`
    }
  })

  const client = new Client({
    name: 'ducktape-ui',
    version: '1.0.0'
  }, {
    capabilities: {
      resources: { subscribe: true }
    }
  })

  await client.connect(transport)
  return client
}
```

**2.3 Agents Client** (Cross-Agent Management)

```typescript
// src/features/agents/mcpClient.ts

import { createMCPClient } from '../mcp/client'
import { writable } from 'svelte/store'

export interface AgentInfo {
  agent_id: string
  capabilities: {
    chat: boolean
    agent_loop: boolean
  }
  mode: 'local' | 'bridge'
  state_uri?: string  // Only present for local agents
}

export const agentList = writable<AgentInfo[]>([])

let agentsClient: Client | null = null
const perAgentStateClients: Map<string, Client> = new Map()

export async function connectAgents(token: string) {
  // Connect to cross-agent management server
  agentsClient = await createMCPClient({
    name: 'agents',
    url: 'http://localhost:8081/mcp/agents',
    token
  })

  // Initial fetch
  await refreshAgentList()

  // Subscribe to agent list updates
  await agentsClient.request({
    method: 'resources/subscribe',
    params: { uri: 'resource://agents/list' }
  })

  // Listen for agent list changes
  agentsClient.on('notification', (notif) => {
    if (notif.method === 'notifications/resources/updated') {
      refreshAgentList()
    }
  })
}

async function refreshAgentList() {
  if (!agentsClient) return

  const result = await agentsClient.request({
    method: 'resources/read',
    params: { uri: 'resource://agents/list' }
  })

  const agents: AgentInfo[] = JSON.parse(result.contents[0].text)
  agentList.set(agents)

  // Connect to state endpoints for local agents
  for (const agent of agents) {
    if (agent.state_uri && !perAgentStateClients.has(agent.agent_id)) {
      await connectAgentState(agent.agent_id, token)
    }
  }
}

async function connectAgentState(agentId: string, token: string) {
  const client = await createMCPClient({
    name: `state_${agentId}`,
    url: `http://localhost:8081/mcp/${agentId}/state`,
    token
  })

  // Subscribe to state updates
  await client.request({
    method: 'resources/subscribe',
    params: { uri: `resource://${agentId}/state` }
  })

  perAgentStateClients.set(agentId, client)
}
```

**2.4 Approvals Client**

```typescript
// src/features/approvals/mcpClient.ts

export async function connectApprovals(agentId: string, token: string) {
  const client = await createMCPClient({
    name: `approvals_${agentId}`,
    url: `http://localhost:8081/mcp/${agentId}/approvals`,
    token
  })

  // Subscribe to approval updates
  await client.request({
    method: 'resources/subscribe',
    params: { uri: 'resource://approval-policy/approvals' }
  })

  return client
}
```

**2.5 Update UI Components**

Replace WebSocket usage with MCP client calls:

```typescript
// Before (WebSocket):
const ws = new WebSocket('ws://localhost:8081/ws/approvals')
ws.onmessage = (msg) => { /* handle approval */ }

// After (MCP):
const client = await connectApprovals(agentId, token)
client.on('notification', async (notif) => {
  if (notif.method === 'notifications/resources/updated') {
    // Refresh approvals from resource
    const approvals = await client.request({
      method: 'resources/read',
      params: { uri: notif.params.uri }
    })
    // Update UI
  }
})
```

### Phase 3: Shared Models (Pydantic → TypeScript)

**3.1 Install Generator**

```bash
npm install --save-dev pydantic-to-typescript
```

**3.2 Configure Generation**

```json
// package.json
{
  "scripts": {
    "generate-types": "pydantic2ts --module adgn.agent.server.protocol --output src/types/protocol.ts",
    "generate-types:watch": "pydantic2ts --module adgn.agent.server.protocol --output src/types/protocol.ts --watch"
  }
}
```

**3.3 Mark Pydantic Models for Export**

Ensure key models are exported:
- `ApprovalBrief`
- `ApprovalPendingEvt`
- `ServerCapabilities`
- `SamplingSnapshot`
- `ServerEntry` (and discriminated union variants)

**3.4 Validation Tests**

```python
# tests/agent/test_type_compatibility.py

def test_typescript_types_match_pydantic():
    """Ensure generated TypeScript matches Python models."""
    # Compare generated JSON schemas
    # Fail if drift detected
```

### Phase 4: Migration & Cleanup

**4.1 Remove WebSocket Stubs**

Delete stub endpoints:
- `/ws/policy`
- `/ws/approvals`
- `/ws/mcp`

**4.2 Update Tests**

- Remove WebSocket test fixtures
- Add MCP client test fixtures
- Test resource subscriptions
- Test notifications

**4.3 Documentation**

Update docs to reflect MCP-based architecture.

## Decisions Summary

### 1. Token Management ✅
- **Session-based** token (valid for server lifetime)
- **Generate new on each boot** (or env var override for configured secret)
- **Store in localStorage** for convenience (graceful fallback if auth fails)
- **No expiry** during server lifetime

### 2. Architecture ✅
- **Multiple independent MCP servers** + cross-agent management server
- **`agents` server** for global agent list
- **Per-agent servers** for approvals, compositor, state
- **Path-based routing** (`/mcp/{agent_id}/approvals`)

### 3. Elicitations ✅
- **Phase in later** (Phase 5+)
- **Keep current approval engine**, add elicitation layer when ready

### 4. Shared Models ✅
- **Auto-generate TypeScript from Pydantic**
- Include all MCP inputs/outputs frontend uses
- Models: `ApprovalBrief`, `ServerCapabilities`, `SamplingSnapshot`, `ServerEntry`, policy models

### 5. Agent Mode Detection ✅
- Check **two factors**:
  - (a) Has chat/UI component
  - (b) Agent loop is under our control
- **Local agents**: Have agent loop + sampling state resource
- **Bridge agents**: No agent loop, no sampling state

### 6. External Agent Sampling State ✅
- **No sampling state** for external agents (we have no way to know)
- Only local agents expose `/mcp/{agent_id}/state` endpoint

### 7. Compositor Forwarding ✅
- Add **basic integration test** for URL translation
- Confirm notifications propagate with correct prefixes

### 8. Browser Compatibility ✅
- **Modern browsers only** (Chrome/Firefox/Safari/Edge last 2 versions)
- No legacy browser support needed

## Open Questions / Research Needed

1. **MCP SDK Browser Bundle Size**: How large is `@modelcontextprotocol/sdk` after bundling?
2. **Streamable HTTP Session Management**: How does SDK handle reconnection?
3. **Resource Notification Performance**: What's the latency for resource updates?
4. **Multiple Concurrent Clients**: Can one frontend have multiple MCP clients open?
   - Research: Yes, one client per server is fine
5. **Compositor URL Translation**: Verify FastMCP proxy correctly prefixes resource URIs
   - From code review: `_ChildHandler` attributes origin, proxy handles prefixing
   - **Confirmed**: Compositor forwards notifications with URL translation

## Implementation Stubs Needed

### Backend Stubs
- [ ] `InfrastructureRegistry.known_agents()` - list all agent IDs
- [ ] **`agents` server** - cross-agent management (lists agents + capabilities)
- [ ] **`state_{agent_id}` server** - per-agent sampling state (local agents only)
- [ ] Path-based routing middleware for MCP servers
- [ ] UI token generation (on boot, with env var override)
- [ ] UI token auth middleware
- [ ] CLI output: print Management UI URL with token
- [ ] Hook agent loop state changes to broadcast state resource updates

### Frontend Stubs
- [ ] MCP client utilities (`createMCPClient`)
- [ ] Token extraction from URL query param
- [ ] Token storage in localStorage (with auth failure fallback)
- [ ] **Agents client** with subscriptions (cross-agent management)
- [ ] **Per-agent state clients** with subscriptions (for local agents)
- [ ] Approvals client with subscriptions
- [ ] Compositor meta client with subscriptions

### Shared Infrastructure
- [ ] Pydantic → TypeScript generator setup
- [ ] Validation tests for type compatibility
- [ ] **Integration test** for compositor URL translation/notification forwarding

## Success Metrics

- [ ] Frontend connects to all MCP servers successfully
- [ ] Resource subscriptions work (notifications received)
- [ ] Approvals flow works end-to-end via MCP
- [ ] Policy updates propagate to UI in real-time
- [ ] MCP server list updates dynamically
- [ ] Token auth prevents unauthorized access
- [ ] No WebSocket code remains
- [ ] TypeScript types match Pydantic models (validated)

## Timeline Estimate

- **Phase 1** (Backend): 2-3 days
- **Phase 2** (Frontend): 2-3 days
- **Phase 3** (Shared Models): 1 day
- **Phase 4** (Migration & Cleanup): 1 day
- **Total**: ~1 week

## References

- [MCP Elicitation Spec](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP Docs](https://github.com/jlowin/fastmcp)
- [Streamable HTTP Transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)

## Notes

- **Compositor notification forwarding**: Verified in `compositor/server.py:121-148`
  - `add_resource_updated_listener` receives notifications from children
  - `_ChildHandler` captures `on_resource_updated` with origin attribution
  - FastMCP proxy handles URI prefixing automatically

- **Existing patterns**: `compositor_meta` server already demonstrates this architecture
  - Uses `NotifyingFastMCP` for broadcasting
  - Listens to compositor mount events
  - Broadcasts resource updates via `broadcast_resource_updated`

- **Resource subscriptions**: Already implemented in `approval_policy/server.py:100-117`
  - `@mcp_server.subscribe_resource()` and `@mcp_server.unsubscribe_resource()` handlers
  - Per-session subscription tracking
  - Works with `NotifyingFastMCP.broadcast_resource_updated()`
