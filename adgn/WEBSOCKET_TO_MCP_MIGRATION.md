# WebSocket to MCP Migration Plan

This document outlines the migration from WebSocket-based communication to MCP (Model Context Protocol) for the agent web UI.

## Overview

**Current Architecture**: Frontend ↔ WebSocket (DELETED) + HTTP REST (broken) ↔ Backend

**Target Architecture**: Frontend ↔ MCP HTTP (`/mcp`) ↔ 2-Level MCP Compositor ↔ FastMCP Servers

## Key Distinction: approval_policy vs approvals Servers

| Server | Purpose | Mounted? | Used By |
|--------|---------|----------|---------|
| **approval_policy** (reader) | Policy evaluation & resources | ✅ Compositor | Agent (reads policy, calls `evaluate_policy`) |
| **approval_policy_proposer** | Create/withdraw policy proposals | ✅ Compositor | Agent (proposes policy changes) |
| **approval_policy_approver** | Admin policy management | ❌ Private client | HTTP endpoints, admin UI |
| **approvals** | User approval actions for tool calls | ✅ Compositor | UI (approve/deny pending calls) |

The `approval_policy` servers handle **policy management** (the rules), while `approvals` handles **user decisions** on pending tool calls.

## 2-Level MCP Compositor Architecture

### Level 1: Global Compositor
**Endpoint**: `/mcp` (streamable HTTP transport)
- Mounts per-agent sub-compositors
- **Status**: Implementation unclear - imports missing `mcp_bridge.compositor_factory`

### Level 2: Per-Agent Sub-Compositors (User-Facing)
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
7. **approval_policy** (3 server instances) - Policy & proposal management
   - **Reader** (`approval_policy`): `ApprovalPolicyServer` - Mounted in user-facing compositor
     - Resources: `resource://approval-policy/policy.py`, `resource://approval-policy/proposals/{id}`
     - Tool: `evaluate_policy(name, arguments)` - Evaluates policy for a tool call via Docker-backed evaluator
     - **Architecture**: `ApprovalPolicyServer` contains all policy business logic and owns two sub-servers:
       - `.proposer`: `NotifyingFastMCP` with proposer tools
       - `.approver`: `NotifyingFastMCP` with admin tools
   - **Proposer** (`approval_policy.proposer`): `policy_server.proposer` - Mounted in user-facing compositor
     - Tools: `create_proposal(content)`, `withdraw_proposal(id)`
   - **Admin** (`approval_policy.approver`): `policy_server.approver` - NOT mounted in compositor (private client only)
     - Tools: `approve_proposal(id)`, `reject_proposal(id)`, `set_policy_text(source)`
     - Access: Via HTTP endpoints or internal client
8. **runtime** - `make_runtime_server()` - Container exec
9. **seatbelt** - `attach_seatbelt_exec()` - Sandboxed exec (optional)

#### ✅ Recently Wired:
10. **approvals** - `adgn/src/adgn/mcp/approvals/server.py` - User approval actions
    - Tools: `approve_call(call_id)`, `deny_abort(call_id)`, `deny_continue(call_id)`
    - Resource: `approvals://pending` - Lists pending approval requests
    - **Status**: Wired to compositor in `container.py:620-622`, broadcasts resource updates on approval changes

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

## Phase 2: Wire Existing Approvals Server ✅ COMPLETED

### Task 2.1: Add __init__.py to approvals module ✅ DONE
**File**: `adgn/src/adgn/mcp/approvals/__init__.py`

```python
from .server import attach_approvals, make_approvals_server, APPROVALS_SERVER_NAME

__all__ = ["attach_approvals", "make_approvals_server", "APPROVALS_SERVER_NAME"]
```

### Task 2.2: Wire approvals server to agent compositor ✅ DONE
**File**: `adgn/src/adgn/agent/runtime/container.py` (lines 620-622)

```python
# Approvals server (approval actions: approve_call, deny_abort, deny_continue)
from adgn.mcp.approvals import attach_approvals
self._approvals_server = await attach_approvals(self._compositor, hub=self.approval_hub)
```

### Task 2.3: Add pending approvals notification to PolicyGatewayMiddleware ✅ DONE
**File**: `adgn/src/adgn/agent/runtime/container.py` (lines 317-321)

The `_pending_notifier` callback now broadcasts MCP resource updates:
```python
async def _pending_notifier(call_id: str, tool_key: str, args_json: str | None) -> None:
    # Broadcast MCP resource update for pending approvals
    if self._approvals_server is not None:
        from adgn.mcp.approvals.server import APPROVALS_PENDING_URI
        await self._approvals_server.broadcast_resource_updated(APPROVALS_PENDING_URI)
```

## Phase 3: Frontend MCP Client Infrastructure ✅ COMPLETED

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

## Phase 4: Migrate Frontend Stores to Existing MCP Resources ✅ COMPLETED

Migrated stores to use MCP tools and resources instead of WebSocket/HTTP.

### Task 4.1: Migrate Approval Actions to MCP Tools ✅ DONE
**Status**: COMPLETE
**File**: `adgn/src/adgn/agent/web/src/features/chat/stores.ts`

Replace broken HTTP calls with MCP tool calls:
- `approveCall()` → `mcp.callTool('approvals_approve_call', { call_id })`
- `denyContinue()` → `mcp.callTool('approvals_deny_continue', { call_id })`
- `deny()` → `mcp.callTool('approvals_deny_abort', { call_id })`

### Task 4.2: Subscribe to Pending Approvals Resource ✅ DONE
**Status**: COMPLETE
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

### Task 4.3: Migrate Policy Operations to MCP Tools ✅ DONE
**Status**: COMPLETE

Replace HTTP policy endpoints with existing `approval_policy` server tools:
- `setPolicy()` → `mcp.callTool('approval_policy.admin_set_policy', { content })`
- `withdrawProposal()` → `mcp.callTool('approval_policy.proposer_withdraw_proposal', { id })`
- `approveProposal()` → `mcp.callTool('approval_policy.admin_approve_proposal', { id })`
- `rejectProposal()` → `mcp.callTool('approval_policy.admin_reject_proposal', { id })`

### Task 4.4: Subscribe to Policy Resources ⏸️ DEFERRED
**Status**: TODO (requires exposing policy resources via MCP)

Subscribe to policy.py and proposals resources:
```typescript
// Subscribe to active policy
await mcpClient.subscribeResource('resource://approval-policy/policy.py', updatePolicyCallback)

// Subscribe to proposals index
await mcpClient.subscribeResource('resource://approval-policy/proposals', updateProposalsCallback)
```

### Task 4.5: Remove WebSocket Import from stores.ts ✅ DONE
**Status**: COMPLETE
**File**: `adgn/src/adgn/agent/web/src/features/chat/stores.ts`

Remove:
```typescript
import { connectWS, type WsClient } from './ws'  // DELETE - file no longer exists
```

## Phase 5: Update UI Components ✅ COMPLETED

### Task 5.1: Update Connection Status Display ⏸️ DEFERRED
**Status**: TODO (can use mcpManager.connectionStatus in RightSidebar)
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

### Task 5.2: Remove WebSocket Connection Calls ✅ DONE
**Status**: COMPLETE

Committed in: `b2f3922d feat(adgn/web): migrate frontend stores to use MCP`
**File**: `adgn/src/adgn/agent/web/src/components/App.svelte`

Remove `connectAgentWs()` / `disconnectAgentWs()` calls, replace with MCP client connection.

## Phase 6: Cleanup Dead Python Code ✅ COMPLETED

### Task 6.1: Remove Dead send_payload Calls ✅ DONE
**Files**:
- `adgn/src/adgn/agent/runtime/container.py` - Removed 4 dead send_payload calls
- `adgn/src/adgn/agent/server/app.py` - Removed dead `_send_snapshot` helper functions

Changes:
- Removed `broadcast_status()` call from container.py (method already deleted)
- Removed ApprovalPendingEvt send_payload call (MCP resource notification replaced it)
- Removed all snapshot send_payload calls (snapshots now fetched via HTTP GET)
- Stubbed out `_push_snapshot()` and `_push_snapshot_and_status()` helper functions

### Task 6.2: Mark Dead Protocol Event Types ✅ DONE
**File**: `adgn/src/adgn/agent/server/protocol.py`

Added docstrings to mark dead event types:
- `Envelope` - WebSocket message wrapper (never instantiated)
- `UiStateSnapshot`, `UiStateUpdated` - Sent via send_payload (no-op)
- `Accepted` - WebSocket acknowledgment (never instantiated)
- `RunStatusEvt` - Sent via send_payload (no-op), replaced by HTTP GET snapshot
- `ApprovalPendingEvt` - Sent via send_payload (no-op), replaced by MCP resource
- `ApprovalDecisionEvt` - Never instantiated, used by reducer but never sent
- `ApprovalApprove`, `ApprovalDenyContinue`, `ApprovalDenyAbort` - Part of dead ApprovalDecisionEvt
- `TurnDone` - WebSocket turn marker (never instantiated)
- `ErrorCode`, `ErrorEvt` - Sent via send_payload (no-op), replaced by HTTP error responses
- `HeartbeatEvt` - WebSocket keepalive (never instantiated)
- `BackpressureEvt` - WebSocket flow control (never instantiated)

Updated ServerMessage union with comments explaining which types are dead vs. still used.

### Task 6.3: Document send_payload as Dead Code ✅ DONE
**File**: `adgn/src/adgn/agent/server/runtime.py`

Added comprehensive docstring to `send_payload()` method explaining:
- Method is now a no-op stub
- All message delivery replaced by HTTP GET, MCP resources, and HTTP error responses
- All calls to this method are effectively dead code
- Kept as stub to avoid breaking existing callers

### Task 6.4: Remove Dead Imports ✅ DONE
**File**: `adgn/src/adgn/agent/runtime/container.py`

Removed unused import: `from adgn.agent.server.protocol import ApprovalPendingEvt`

## Deferred: Requires New MCP Servers

These tasks cannot be completed until new MCP servers are created:

### ⏸️ Agent Control Server (send_prompt, abort_run)
- Current: Frontend calls HTTP `/api/agents/{id}/prompt` and `/api/agents/{id}/abort`
- Needs: New MCP server with `send_prompt` and `abort_run` tools
- When created: Update stores.ts to call MCP tools instead

### ⏸️ Agents Management Server (create_agent, delete_agent, list_agents)
- Current: Frontend calls `/api/agents` HTTP endpoints
- Needs: New global MCP server with agent lifecycle tools
- When created: Update agent stores to use MCP tools

### ⏸️ Agent Status/Snapshot Resources
- Current: Frontend calls `/api/agents/{id}/snapshot` and `/api/agents/{id}/status`
- Needs: Expose as MCP resources (`agent://{id}/snapshot`, `agent://{id}/status`)
- When created: Subscribe to resources instead of polling HTTP

### ⏸️ Future Cleanup (Low Priority)
- Remove dead protocol event types entirely (after verifying no external dependencies)
- Remove send_payload method stub (after verifying all callers removed)
- Clean up remaining send_payload calls in runtime.py (ErrorEvt, RunStatusEvt, etc.)

## Success Criteria

- [ ] Zero WebSocket references in codebase (verified with `grep`)
- [ ] All UI functionality works (agent list, approvals, policy, commands)
- [ ] Real-time updates work correctly
- [ ] Connection resilience tested (server restart, network interruption)
- [ ] Performance is equal or better than WebSocket implementation
