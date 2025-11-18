# MCP-Based Management UI Plan

## Executive Summary

Replace custom WebSocket channels with MCP protocol for the Management UI. The frontend will be an MCP client connecting to multiple independent MCP servers via Streamable HTTP. This provides a clean security boundary, reuses MCP infrastructure, and enables future features like elicitations for approvals.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Browser)                    │
│  - Multiple MCP clients (one per server)                    │
│  - Uses @modelcontextprotocol/sdk (Streamable HTTP)         │
│  - Token in URL query param (auto-inserted)                 │
└──────────────┬──────────────────────────────────────────────┘
               │ HTTP GET /ui?token=...
               │ Streamable HTTP to each MCP server
               ▼
┌─────────────────────────────────────────────────────────────┐
│              Management UI Server (Port 8081)                │
│  - Serves static frontend files                             │
│  - Token authentication middleware                          │
│  - Exposes multiple independent MCP servers:                │
│    • agent_meta: List agents, sampling state                │
│    • approval_policy_{agent_id}: Per-agent approvals/policy │
│    • compositor_meta_{agent_id}: Per-agent MCP server list  │
└─────────────────────────────────────────────────────────────┘
               ▲
               │ Multi-tenant infrastructure registry
               │ (routes requests to correct agent)
               │
┌─────────────────────────────────────────────────────────────┐
│             MCP Server (Port 8080)                          │
│  - Token-authenticated MCP endpoint (/sse)                  │
│  - Routes to per-agent compositor                           │
│  - For external agents (ChatGPT, etc.)                      │
└─────────────────────────────────────────────────────────────┘
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

**Recommendation**: Use multiple independent servers. The compositor_meta pattern already exists and works well.

### 2. Per-Agent Routing

**Option A: Independent MCP Servers Per Agent**
```
/mcp/agent_meta               → Lists all agents
/mcp/{agent_id}/approvals     → Per-agent approval server
/mcp/{agent_id}/compositor    → Per-agent server list
```

**Option B: Agent ID in Request Context**
- Use MCP request parameters to specify agent
- Single endpoint per server type

**Recommendation**: Option A (path-based routing). More RESTful, clearer routing logic.

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

**Questions**:
- Should token be single-use or session-based?
  - **Recommendation**: Session-based (valid for server lifetime)
- Should token expire?
  - **Recommendation**: No expiry (local dev tool), but support manual revocation
- Store token in localStorage or keep in URL?
  - **Recommendation**: localStorage after initial load for convenience

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

**Questions**:
- Use elicitations immediately or phase in later?
  - **Recommendation**: Phase 2 (after basic MCP migration works)
- Keep current approval engine or redesign for elicitations?
  - **Recommendation**: Keep engine, add elicitation layer on top

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

**Recommendation**: Option A (Pydantic → TypeScript). Python is the authoritative backend.

**Implementation**:
```bash
# Add to package.json
"scripts": {
  "generate-types": "pydantic2ts --module adgn.agent.server.protocol --output src/types/protocol.ts"
}
```

## Implementation Plan

### Phase 1: Backend - Independent MCP Servers

**1.1 Agent Meta Server** (`agent_meta`)

Exposes list of known agents and their sampling state.

```python
# adgn/src/adgn/agent/mcp_bridge/servers/agent_meta.py

from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

def make_agent_meta_server(registry: InfrastructureRegistry) -> NotifyingFastMCP:
    """Expose agent list and sampling state."""
    server = NotifyingFastMCP(
        name="agent_meta",
        instructions="Management metadata for all agents."
    )

    @server.resource(
        "resource://agent_meta/agents",
        name="agents.list",
        mime_type="application/json"
    )
    async def list_agents():
        """List all known agents with their state."""
        agents = []
        for agent_id in registry.known_agents():
            infra, _ = await registry.get_or_create_infrastructure(agent_id)
            # For local agents: include sampling state
            # For bridge mode: indicate external agent
            agents.append({
                "agent_id": agent_id,
                "mode": "local" if infra.has_chat else "bridge",
                "sampling_state": await infra.get_sampling_state() if hasattr(infra, 'get_sampling_state') else None,
            })
        return agents

    return server
```

**Questions**:
- How to determine if agent is "local" vs "bridge"?
  - Check if chat component exists in capabilities?
- Include sampling state for external agents?
  - **Recommendation**: No, only for local agents

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

**1.4 Token Authentication Middleware**

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

**1.5 Path-Based Routing to MCP Servers**

```python
# Route requests to correct MCP server based on path

@app.get("/mcp/agent_meta")
async def agent_meta_endpoint():
    # Serve agent_meta MCP server via Streamable HTTP
    pass

@app.get("/mcp/{agent_id}/approvals")
async def approval_endpoint(agent_id: str):
    # Serve approval server for agent_id
    pass

@app.get("/mcp/{agent_id}/compositor")
async def compositor_endpoint(agent_id: str):
    # Serve compositor_meta server for agent_id
    pass
```

**Questions**:
- Use FastMCP's built-in Streamable HTTP handler or custom?
  - **Recommendation**: Use `fastmcp.server.run_streamable_http` per-server
- How to serve multiple MCP servers on same port?
  - FastAPI sub-applications or manual routing?
  - **Recommendation**: FastAPI sub-apps mounted at different paths

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

**2.3 Agent Meta Client**

```typescript
// src/features/agents/mcpClient.ts

import { createMCPClient } from '../mcp/client'
import { writable } from 'svelte/store'

export interface AgentInfo {
  agent_id: string
  mode: 'local' | 'bridge'
  sampling_state?: SamplingState
}

export const agentList = writable<AgentInfo[]>([])

let metaClient: Client | null = null

export async function connectAgentMeta(token: string) {
  metaClient = await createMCPClient({
    name: 'agent_meta',
    url: 'http://localhost:8081/mcp/agent_meta',
    token
  })

  // Initial fetch
  await refreshAgentList()

  // Subscribe to updates
  await metaClient.request({
    method: 'resources/subscribe',
    params: { uri: 'resource://agent_meta/agents' }
  })

  // Listen for resource updates
  metaClient.on('notification', (notif) => {
    if (notif.method === 'notifications/resources/updated') {
      refreshAgentList()
    }
  })
}

async function refreshAgentList() {
  if (!metaClient) return

  const result = await metaClient.request({
    method: 'resources/read',
    params: { uri: 'resource://agent_meta/agents' }
  })

  agentList.set(JSON.parse(result.contents[0].text))
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

## Questions for User

### 1. Token Management
- **Q**: Should the UI token be single-use or session-based?
- **Q**: Should tokens expire, or valid for server lifetime?
- **Q**: Store token in localStorage or keep in URL?

### 2. Architecture
- **Q**: Prefer multiple independent MCP servers or single meta compositor?
  - My recommendation: Multiple independent servers
- **Q**: Use path-based routing (`/mcp/{agent_id}/approvals`) or request params?
  - My recommendation: Path-based routing

### 3. Elicitations
- **Q**: Use MCP elicitations for approvals immediately or phase in later?
  - My recommendation: Phase in later (Phase 5)
- **Q**: Keep current approval engine or redesign for elicitations?
  - My recommendation: Keep engine, add elicitation layer

### 4. Shared Models
- **Q**: Generate TypeScript from Pydantic, or manual maintenance?
  - My recommendation: Auto-generate from Pydantic
- **Q**: Which models should be shared?
  - My candidates: `ApprovalBrief`, `ServerCapabilities`, `SamplingSnapshot`, `ServerEntry`

### 5. Compositor Forwarding
- **Q**: I verified compositor forwards resource notifications. Should we add URL translation tests?
  - The `_ChildHandler` captures notifications with origin attribution
  - FastMCP proxy handles prefix translation automatically
  - Should we add explicit tests for this?

### 6. Agent Metadata
- **Q**: How to determine if agent is "local" vs "bridge"?
  - Check for chat capability?
  - Explicit flag in infrastructure?
- **Q**: Should external agents have any "sampling state" concept?
  - My recommendation: No, only local agents

### 7. Browser Compatibility
- **Q**: Need to support older browsers?
  - Vite already bundles, should be fine
  - `@modelcontextprotocol/sdk` works in modern browsers

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
- [ ] `agent_meta` server implementation
- [ ] Path-based routing middleware for MCP servers
- [ ] UI token generation and CLI printing
- [ ] UI token auth middleware

### Frontend Stubs
- [ ] MCP client utilities (`createMCPClient`)
- [ ] Token extraction from URL query param
- [ ] Agent meta client with subscriptions
- [ ] Approvals client with subscriptions
- [ ] Compositor meta client with subscriptions

### Shared Infrastructure
- [ ] Pydantic → TypeScript generator setup
- [ ] Validation tests for type compatibility

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
