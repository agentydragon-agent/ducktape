# WebSocket to MCP Migration Plan

This document outlines the migration from WebSocket-based communication to MCP (Model Context Protocol) for the agent web UI.

## Overview

**Current Architecture**: Frontend ↔ WebSocket (DELETED) + HTTP REST (broken) ↔ Backend

**Target Architecture**: Frontend ↔ MCP HTTP (`/mcp`) ↔ 2-Level MCP Compositor ↔ FastMCP Servers

## 2-Level MCP Compositor Architecture

### Level 1: Global Compositor
**Endpoint**: `/mcp` (streamable HTTP transport)
- Mounts per-agent sub-compositors
- **Status**: Implementation unclear - imports missing `mcp_bridge.compositor_factory`

### Level 2: Per-Agent Sub-Compositors
Each `AgentContainer` has a `_compositor: Compositor` that mounts small FastMCP servers:

#### ✅ Existing Standard Servers (mounted via `mount_standard_inproc_servers`):
1. **resources** - `make_resources_server()` - Aggregates resources from all servers
   - Tools: `resources_list`, `resources_read` (with windowing)
2. **compositor_meta** - `make_compositor_meta_server()` - Compositor state/metadata
3. **compositor_admin** - `make_compositor_admin_server()` - Mount lifecycle
   - Tools: `attach_server`, `detach_server`

#### ✅ Existing Agent-Specific Servers:
4. **chat.human** & **chat.assistant** - `make_chat_server()` - Chat message stores
   - Tools: `post(mime, content)`, `read_pending_messages(limit?)`
   - Resources: `chat://head`, `chat://last-read`, `chat://messages/{id}`
5. **ui** - `make_ui_server()` - UI message display
   - Tools: `send_message(mime, content)`, `end_turn()`
6. **loop** - `make_loop_server()` - Loop control
   - Tools: `yield_turn()`
7. **approval_policy** (3 variants) - Policy & proposal management
   - Reader: Resources for `resource://approval-policy/policy.py`, `proposals/{id}`
   - Proposer: Tools: `create_proposal`, `withdraw_proposal`
   - Admin: Tools: `approve_proposal`, `reject_proposal`, `set_policy`
8. **runtime** - `make_runtime_server()` - Container exec
9. **seatbelt** - `attach_seatbelt_exec()` - Sandboxed exec (optional)

#### ⚠️ CREATED BUT NOT WIRED:
10. **approvals** - `/mcp/approvals/server.py` - Approval actions (JUST CREATED)
    - Tools: `approve_call`, `deny_abort`, `deny_continue`
    - Resource: `approvals://pending`
    - **TODO**: Wire to agent compositors, add ApprovalHub notification

#### ❌ MISSING:
11. **Agent control tools** - `send_prompt`, `abort_run` (need to create server)
12. **Global agents management** - `create_agent`, `delete_agent`, `list_agents`, `boot_agent` (need to find or create)

## Background

WebSocket files were deleted in Phase 1. Frontend HTTP REST endpoints (`/api/agents/{id}/approve`, etc.) don't exist on backend - they should be replaced with MCP tool calls.

## Phase 1: Backend Cleanup ✅ COMPLETED

### Task 1.1: Delete Dead WebSocket Files ✅ DONE
Deleted files:
- `adgn/src/adgn/agent/server/ws.py` (415 lines)
- `adgn/src/adgn/agent/server/agents_ws.py` (entire file)
- `adgn/src/adgn/agent/web/src/features/chat/ws.ts` (64 lines)

Committed in: `fb481138 refactor(adgn): remove dead WebSocket infrastructure`

### Task 1.2: Remove WebSocket Code from ConnectionManager ✅ DONE
**File**: `adgn/src/adgn/agent/server/runtime.py`

Removed:
- `from adgn.agent.server.agents_ws import AgentsWSHub` import
- `_status_hub` and `_status_agent_id` fields from ConnectionManager
- `configure_status_hub()` and `broadcast_status()` methods
- All calls to `broadcast_status()` throughout the file

Committed in: `fb481138 refactor(adgn): remove dead WebSocket infrastructure`

## Phase 2: Wire Existing Approvals Server ⚠️ IN PROGRESS

### Task 2.1: Add __init__.py to approvals module
**Status**: TODO

Create `adgn/src/adgn/mcp/approvals/__init__.py`:
```python
from .server import attach_approvals, make_approvals_server, APPROVALS_SERVER_NAME

__all__ = ["attach_approvals", "make_approvals_server", "APPROVALS_SERVER_NAME"]
```

### Task 2.2: Wire approvals server to agent compositor
**Status**: TODO
**File**: `adgn/src/adgn/agent/runtime/container.py`

Add approvals server mounting after chat servers (around line 620):
```python
# After attach_persisted_chat_servers call:
from adgn.mcp.approvals.server import attach_approvals

# Mount approvals server with ApprovalHub
await attach_approvals(self._compositor, hub=self.approval_hub)
```

### Task 2.3: Add pending approvals notification to PolicyGatewayMiddleware
**Status**: TODO
**File**: `adgn/src/adgn/mcp/policy_gateway/middleware.py`

Update `pending_notifier` callback to also notify the approvals resource when a new approval is pending (around line 250).

## Phase 3: Frontend MCP Client Infrastructure ❌ NOT STARTED

### Task 3.1: Add MCP SDK Dependency
**Status**: TODO

```bash
cd adgn/src/adgn/agent/web
pnpm add @modelcontextprotocol/sdk
```

### Task 3.2: Create MCP Client Wrapper
**Status**: TODO
**New File**: `adgn/src/adgn/agent/web/src/features/mcp/client.ts`

Create client wrapper that connects to `/mcp` endpoint via SSE transport.
See implementation in appendix below.

### Task 3.3: Create MCP Store Manager
**Status**: TODO
**New File**: `adgn/src/adgn/agent/web/src/features/mcp/manager.ts`

Manages per-agent MCP client connections and provides connection status store.
See implementation in appendix below.

## Phase 4: Migrate Frontend Stores to Existing MCP Resources ❌ NOT STARTED

Focus on using **existing** MCP servers only. Deferred items that require new servers are listed separately.

### Task 4.1: Migrate Approval Actions to MCP Tools ✅ CAN DO NOW
**Status**: TODO
**File**: `adgn/src/adgn/agent/web/src/features/chat/stores.ts`

Replace broken HTTP calls with MCP tool calls:
- `approveCall()` → `mcp.callTool('approvals_approve_call', { call_id })`
- `denyContinue()` → `mcp.callTool('approvals_deny_continue', { call_id })`
- `deny()` → `mcp.callTool('approvals_deny_abort', { call_id })`

### Task 4.2: Subscribe to Pending Approvals Resource ✅ CAN DO NOW
**Status**: TODO
**File**: `adgn/src/adgn/agent/web/src/features/chat/stores.ts`

Replace WebSocket pending approvals with MCP resource subscription:
```typescript
// Subscribe to approvals://pending resource
const unsubscribe = await mcpClient.subscribeResource<{ pending: PendingApproval[] }>(
  'approvals://pending',
  (data) => {
    const map = new Map(data.pending.map(p => [p.call_id, p]))
    pendingApprovals.set(map)
  }
)
```

### Task 4.3: Migrate Policy Operations to MCP Tools ✅ CAN DO NOW
**Status**: TODO

Replace HTTP policy endpoints with existing `approval_policy` server tools:
- `setPolicy()` → `mcp.callTool('approval_policy.admin_set_policy', { content })`
- `withdrawProposal()` → `mcp.callTool('approval_policy.proposer_withdraw_proposal', { id })`
- `approveProposal()` → `mcp.callTool('approval_policy.admin_approve_proposal', { id })`
- `rejectProposal()` → `mcp.callTool('approval_policy.admin_reject_proposal', { id })`

### Task 4.4: Subscribe to Policy Resources ✅ CAN DO NOW
**Status**: TODO

Subscribe to policy.py and proposals resources:
```typescript
// Subscribe to active policy
await mcpClient.subscribeResource('resource://approval-policy/policy.py', updatePolicyCallback)

// Subscribe to proposals index
await mcpClient.subscribeResource('resource://approval-policy/proposals', updateProposalsCallback)
```

### Task 4.5: Remove WebSocket Import from stores.ts ✅ CAN DO NOW
**Status**: TODO
**File**: `adgn/src/adgn/agent/web/src/features/chat/stores.ts`

Remove:
```typescript
import { connectWS, type WsClient } from './ws'  // DELETE - file no longer exists
```

## Phase 5: Update UI Components ❌ NOT STARTED

### Task 5.1: Update Connection Status Display
**Status**: TODO
**File**: `adgn/src/adgn/agent/web/src/components/RightSidebar.svelte`

Replace WebSocket connection status with MCP connection status:
```svelte
<script>
  import { mcpManager } from '../features/mcp/manager'
  const { connectionStatus } = mcpManager
</script>

{#if !$connectionStatus.connected}
  <div class="error">MCP disconnected: {$connectionStatus.error || 'Unknown'}</div>
{/if}
```

### Task 5.2: Remove WebSocket Connection Calls
**Status**: TODO
**File**: `adgn/src/adgn/agent/web/src/components/App.svelte`

Remove `connectAgentWs()` / `disconnectAgentWs()` calls, replace with MCP client connection.

## Deferred: Requires New MCP Servers

These tasks cannot be completed until new MCP servers are created:

### ⏸️ Agent Control Server (send_prompt, abort_run)
- Current: Frontend calls broken `/api/agents/{id}/prompt` and `/api/agents/{id}/abort`
- Needs: New MCP server with `send_prompt` and `abort_run` tools
- When created: Update stores to call MCP tools instead

### ⏸️ Agents Management Server (create_agent, delete_agent, list_agents)
- Current: Frontend calls `/api/agents` HTTP endpoints
- Needs: New global MCP server with agent lifecycle tools
- When created: Update agent stores to use MCP tools

### ⏸️ Agent Status/Snapshot Resources
- Current: Frontend calls `/api/agents/{id}/snapshot` and `/api/agents/{id}/status`
- Needs: Expose as MCP resources (`agent://{id}/snapshot`, `agent://{id}/status`)
- When created: Subscribe to resources instead of polling HTTP

## Appendix: Implementation Details

### MCP Client Wrapper Implementation
```typescript
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js'

export interface McpClientOptions {
  agentId?: string
}

export class AgentMcpClient {
  private client: Client
  private transport: SSEClientTransport

  private constructor(client: Client, transport: SSEClientTransport) {
    this.client = client
    this.transport = transport
  }

  static async connect(options: McpClientOptions = {}): Promise<AgentMcpClient> {
    const url = options.agentId
      ? `${window.location.origin}/mcp?agent_id=${options.agentId}`
      : `${window.location.origin}/mcp`

    const transport = new SSEClientTransport(new URL(url))
    const client = new Client(
      { name: 'adgn-web', version: '1.0.0' },
      { capabilities: { resources: { subscribe: true } } }
    )

    await client.connect(transport)
    return new AgentMcpClient(client, transport)
  }

  // Tool call wrappers
  async callTool<T = unknown>(name: string, args: Record<string, unknown>): Promise<T> {
    const result = await this.client.callTool({ name, arguments: args })
    return result.content[0] as T
  }

  // Resource subscription
  async subscribeResource<T>(
    uri: string,
    callback: (data: T) => void
  ): Promise<() => void> {
    await this.client.subscribeResource({ uri })

    // Poll for resource updates
    let active = true
    const poll = async () => {
      while (active) {
        try {
          const result = await this.client.readResource({ uri })
          if (result.contents?.[0]) {
            const data = JSON.parse(result.contents[0].text) as T
            callback(data)
          }
        } catch (e) {
          console.error(`Resource subscription error: ${uri}`, e)
        }
        await new Promise(r => setTimeout(r, 1000))
      }
    }

    poll()
    return () => { active = false }
  }

  async close(): Promise<void> {
    await this.client.close()
  }
}
```

### Task 2.3: Create MCP Store Manager
**Priority**: High
**Estimate**: 1.5 hours
**New File**: `adgn/src/adgn/agent/web/src/features/mcp/manager.ts`

**Implementation**:
```typescript
import { writable, type Writable } from 'svelte/store'
import { AgentMcpClient } from './client'

export interface ConnectionStatus {
  connected: boolean
  error: string | null
}

class McpManager {
  // Global agents client
  private globalClient: AgentMcpClient | null = null

  // Per-agent clients
  private agentClients = new Map<string, AgentMcpClient>()

  // Connection status store
  public connectionStatus: Writable<ConnectionStatus> = writable({
    connected: false,
    error: null
  })

  async connectGlobal(): Promise<AgentMcpClient> {
    if (this.globalClient) return this.globalClient

    try {
      this.globalClient = await AgentMcpClient.connect()
      this.connectionStatus.set({ connected: true, error: null })
      return this.globalClient
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e)
      this.connectionStatus.set({ connected: false, error })
      throw e
    }
  }

  async connectAgent(agentId: string): Promise<AgentMcpClient> {
    const existing = this.agentClients.get(agentId)
    if (existing) return existing

    try {
      const client = await AgentMcpClient.connect({ agentId })
      this.agentClients.set(agentId, client)
      this.connectionStatus.set({ connected: true, error: null })
      return client
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e)
      this.connectionStatus.set({ connected: false, error })
      throw e
    }
  }

  async disconnectAgent(agentId: string): Promise<void> {
    const client = this.agentClients.get(agentId)
    if (client) {
      await client.close()
      this.agentClients.delete(agentId)
    }
  }

  getGlobalClient(): AgentMcpClient | null {
    return this.globalClient
  }

  getAgentClient(agentId: string): AgentMcpClient | null {
    return this.agentClients.get(agentId) || null
  }
}

export const mcpManager = new McpManager()
```

## Phase 3: Migrate Stores to MCP

### Task 3.1: Migrate Agents List Store
**Priority**: High
**Estimate**: 2 hours
**File**: `adgn/src/adgn/agent/web/src/features/agents/stores.ts`

**Changes**:
1. Remove WebSocket code:
   - Delete `_ws` variable
   - Delete `startAgentsWebsocket()` function
   - Delete all WebSocket event handlers

2. Add MCP subscription:
   ```typescript
   import { mcpManager } from '../mcp/manager'

   export async function startAgentsSubscription() {
     const client = await mcpManager.connectGlobal()

     const unsubscribe = await client.subscribeResource<{ agents: AgentDescriptor[] }>(
       'agents://list',
       (data) => {
         agentsList.set(data.agents)
       }
     )

     // Store cleanup function
     return unsubscribe
   }
   ```

**MCP Resource**: `agents://list`
**Backend**: Should expose agent list with live status updates

### Task 3.2: Migrate Chat Store
**Priority**: High
**Estimate**: 3 hours
**File**: `adgn/src/adgn/agent/web/src/features/chat/stores.ts`

**Changes**:
1. Remove WebSocket imports and `connectWS()` usage

2. Replace with MCP client:
   ```typescript
   import { mcpManager } from '../mcp/manager'

   let currentAgentClient: AgentMcpClient | null = null
   let unsubscribers: Array<() => void> = []

   export async function connectToAgent(agentId: string) {
     // Clean up previous connection
     if (currentAgentClient) {
       unsubscribers.forEach(fn => fn())
       unsubscribers = []
     }

     const client = await mcpManager.connectAgent(agentId)
     currentAgentClient = client

     // Subscribe to snapshot (includes approvals, policy, etc.)
     const unsubSnapshot = await client.subscribeResource<Snapshot>(
       `agent://${agentId}/snapshot`,
       (snapshot) => {
         // Update all related stores
         currentSnapshot.set(snapshot)
         runStatus.set(snapshot.run_status || 'idle')
         pendingApprovals.set(new Map(
           snapshot.approvals.map(a => [a.call_id, a])
         ))
         approvalPolicy.set(snapshot.policy)
         mcpServerEntries.set(snapshot.mcp_servers || [])
       }
     )

     unsubscribers.push(unsubSnapshot)
   }
   ```

**MCP Resources**:
- `agent://{id}/snapshot` - Full agent state snapshot

### Task 3.3: Migrate Command Functions to MCP Tools
**Priority**: High
**Estimate**: 2 hours
**Files**:
- `adgn/src/adgn/agent/web/src/features/chat/stores.ts`
- `adgn/src/adgn/agent/web/src/features/agents/api.ts`

**Changes for chat/stores.ts**:
```typescript
// Approval commands
export async function approve(call_id: string) {
  const client = mcpManager.getAgentClient($currentAgentId)
  if (!client) throw new Error('Not connected to agent')

  await client.callTool('approve_call', { call_id })
}

export async function denyContinue(call_id: string) {
  const client = mcpManager.getAgentClient($currentAgentId)
  if (!client) throw new Error('Not connected to agent')

  await client.callTool('deny_continue', { call_id })
}

export async function deny(call_id: string) {
  const client = mcpManager.getAgentClient($currentAgentId)
  if (!client) throw new Error('Not connected to agent')

  await client.callTool('deny_abort', { call_id })
}

// Policy commands
export async function setPolicy(content: string) {
  const client = mcpManager.getAgentClient($currentAgentId)
  if (!client) throw new Error('Not connected to agent')

  await client.callTool('set_policy', { content })
}

export async function approveProposal(id: string) {
  const client = mcpManager.getAgentClient($currentAgentId)
  if (!client) throw new Error('Not connected to agent')

  await client.callTool('approve_proposal', { id })
}

export async function withdrawProposal(id: string) {
  const client = mcpManager.getAgentClient($currentAgentId)
  if (!client) throw new Error('Not connected to agent')

  await client.callTool('withdraw_proposal', { id })
}
```

**Changes for agents/api.ts**:
```typescript
import { mcpManager } from '../mcp/manager'

export async function createAgent(preset: string, system?: string) {
  const client = mcpManager.getGlobalClient()
  if (!client) throw new Error('Not connected')

  return await client.callTool<{ id: string }>('create_agent', {
    preset,
    system
  })
}

export async function deleteAgent(agentId: string) {
  const client = mcpManager.getGlobalClient()
  if (!client) throw new Error('Not connected')

  await client.callTool('delete_agent', { agent_id: agentId })
}

export async function bootAgent(agentId: string) {
  const client = mcpManager.getGlobalClient()
  if (!client) throw new Error('Not connected')

  await client.callTool('boot_agent', { agent_id: agentId })
}

export async function attachMcpServer(agentId: string, name: string, spec: unknown) {
  const client = mcpManager.getAgentClient(agentId)
  if (!client) throw new Error('Not connected to agent')

  await client.callTool('attach_mcp_server', { name, spec })
}

export async function detachMcpServer(agentId: string, name: string) {
  const client = mcpManager.getAgentClient(agentId)
  if (!client) throw new Error('Not connected to agent')

  await client.callTool('detach_mcp_server', { name })
}
```

**MCP Tools Required**:
- `approve_call` - Approve pending tool call
- `deny_continue` - Deny but continue execution
- `deny_abort` - Deny and abort run
- `set_policy` - Update approval policy
- `approve_proposal` - Approve policy proposal
- `withdraw_proposal` - Withdraw policy proposal
- `create_agent` - Create new agent
- `delete_agent` - Delete agent
- `boot_agent` - Start agent container
- `attach_mcp_server` - Attach MCP server to agent
- `detach_mcp_server` - Detach MCP server from agent

## Phase 4: Update UI Components

### Task 4.1: Update Controller
**Priority**: High
**Estimate**: 1 hour
**File**: `adgn/src/adgn/agent/web/src/features/controller.ts`

**Changes**:
1. Replace `startAgentsWebsocket()` with `startAgentsSubscription()`
2. Replace `connectWS()` with `connectToAgent()` from chat stores
3. Update lifecycle management to use MCP manager

### Task 4.2: Update RightSidebar Connection Status
**Priority**: Medium
**Estimate**: 30 minutes
**File**: `adgn/src/adgn/agent/web/src/components/RightSidebar.svelte`

**Changes**:
```svelte
<script lang="ts">
  import { mcpManager } from '../features/mcp/manager'

  const mcpStatus = mcpManager.connectionStatus
</script>

<div class="mcp-status"
  title={$mcpStatus.connected
    ? 'MCP connected (browser ↔ server). Controls live updates.'
    : 'MCP disconnected. ' + ($mcpStatus.error || 'Reconnecting...')}>
  <span class="dot {$mcpStatus.connected ? 'on' : 'off'}"></span>
  <span>{$mcpStatus.connected ? 'MCP connected' : 'MCP disconnected'}</span>
</div>
```

Update CSS:
```css
/* Rename .ws to .mcp-status */
.mcp-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
```

### Task 4.3: Update App.svelte
**Priority**: Medium
**Estimate**: 20 minutes
**File**: `adgn/src/adgn/agent/web/src/App.svelte`

**Changes**:
- Remove WebSocket-related comments
- Add MCP initialization in `onMount()`

## Phase 5: Cleanup and Configuration

### Task 5.1: Delete Dead Frontend Files
**Priority**: High
**Estimate**: 10 minutes

**Files to delete**:
- `adgn/src/adgn/agent/web/src/features/chat/ws.ts`

**Command**:
```bash
git rm adgn/src/adgn/agent/web/src/features/chat/ws.ts
```

### Task 5.2: Remove WebSocket Package Dependency
**Priority**: Low
**Estimate**: 5 minutes

**Check if still needed**:
```bash
cd adgn/src/adgn/agent/web
grep -r "import.*ws\|require.*ws" src/
```

If not used, remove:
```bash
pnpm remove ws
```

### Task 5.3: Update Vite Configuration
**Priority**: Medium
**Estimate**: 10 minutes
**File**: `adgn/src/adgn/agent/web/vite.config.ts`

**Changes**:
```typescript
// Remove WebSocket proxy configuration
proxy: {
  '/mcp': {
    target: backendOrigin,
    changeOrigin: true,
  },
  // DELETE: '/ws': { ... }
}
```

### Task 5.4: Update CLI Logging
**Priority**: Low
**Estimate**: 10 minutes
**File**: `adgn/src/adgn/agent/cli.py`

**Changes**:
```python
# Remove WebSocket logger configuration (lines ~113-114):
# DELETE:
logging.getLogger("websockets.client").setLevel(logging.INFO)
logging.getLogger("websockets.server").setLevel(logging.INFO)
```

### Task 5.5: Update README
**Priority**: Low
**Estimate**: 15 minutes
**File**: `adgn/src/adgn/agent/README.md`

**Changes**:
- Replace "WebSocket UI" with "MCP UI"
- Update architecture description to mention MCP instead of WebSocket
- Update proxy configuration notes
- Remove WebSocket diagnostic notes

## Testing Checklist

After completing each phase:

- [ ] **Phase 1**: Backend starts without errors, no WebSocket endpoints registered
- [ ] **Phase 2**: MCP client can connect to `/mcp` endpoint
- [ ] **Phase 3**:
  - [ ] Agent list updates in real-time
  - [ ] Agent status updates when run starts/stops
  - [ ] Approvals appear in UI
  - [ ] All commands work (approve, deny, etc.)
- [ ] **Phase 4**:
  - [ ] Connection status indicator shows correct state
  - [ ] UI updates when MCP connection lost/restored
- [ ] **Phase 5**:
  - [ ] No WebSocket references in codebase
  - [ ] Frontend builds without errors
  - [ ] All existing functionality works

## Migration Strategy

**Recommended Approach**: Feature flag with dual implementation

1. Add feature flag: `VITE_USE_MCP=true`
2. Implement MCP code alongside WebSocket code
3. Test MCP implementation thoroughly
4. Switch default to MCP
5. Remove WebSocket code after verification

**Alternative**: Direct cutover (faster but riskier)
1. Implement all MCP code
2. Delete WebSocket code
3. Test and fix issues

## Rollback Plan

If critical issues arise during migration:

1. Revert to previous commit
2. Document issues encountered
3. Address issues in MCP implementation
4. Retry migration

## Success Criteria

- [ ] Zero WebSocket references in codebase (verified with `grep`)
- [ ] All UI functionality works (agent list, approvals, policy, commands)
- [ ] Real-time updates work correctly
- [ ] Connection resilience tested (server restart, network interruption)
- [ ] Performance is equal or better than WebSocket implementation

## Timeline Estimate

- **Phase 1**: 1 hour (backend cleanup)
- **Phase 2**: 4 hours (MCP client infrastructure)
- **Phase 3**: 7 hours (migrate stores and commands)
- **Phase 4**: 2 hours (update UI)
- **Phase 5**: 1 hour (cleanup)
- **Testing**: 3 hours
- **Buffer**: 2 hours

**Total**: ~20 hours (2.5 days for one developer)
