# Frontend HTTP/WebSocket to MCP Migration Audit

**Generated:** 2025-11-19
**Scope:** `/home/user/ducktape/adgn/src/adgn/agent/web/src/`

This audit identifies all HTTP REST API calls and WebSocket connections in the frontend that should be migrated to MCP, based on the migration plan in `plan.md`.

---

## Summary

- **HTTP calls to migrate:** 5 endpoints
- **HTTP calls OK to keep:** 2 endpoints (capabilities, presets)
- **HTTP calls deferred:** 1 endpoint (send_message - out of Phase 1-5 scope)
- **WebSocket channels to migrate:** 6 channels

---

## HTTP REST API Calls

### 🔴 NEEDS MIGRATION (5 endpoints)

#### 1. GET `/api/agents/{id}/approvals/history`
- **File:** `src/components/ApprovalTimeline.svelte:29`
- **Current:** Direct `fetch()` call
- **MCP Equivalent:** `resource://agents/{id}/approvals/history`
- **Status:** MCP function already exists in `api.ts` as `getApprovalHistory()`, but component bypasses it
- **Action Required:** Update component to use `getApprovalHistory()` from api.ts

```typescript
// Current (line 29):
const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/approvals/history`
const res = await fetch(url)

// Should be:
import { getApprovalHistory } from '../features/agents/api'
const data = await getApprovalHistory(agentId)
```

#### 2. GET `/api/agents/{id}/policy`
- **File:** `src/components/PolicyEditorPane.svelte:39`
- **Current:** Direct `fetch()` call
- **MCP Equivalent:** `resource://agents/{id}/approval-policy/policy.py`
- **Status:** ⚠️ NOT YET in api.ts
- **Action Required:**
  1. Add `getPolicy(agentId)` function to api.ts using MCP resource
  2. Update component to use new function

```typescript
// Current (line 39):
const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/policy`
const res = await fetch(url)

// Should add to api.ts:
export async function getPolicy(agentId: string): Promise<PolicyInfo> {
  const client = await getMCPClient()
  const result = await readResource(client, `resource://agents/${agentId}/approval-policy/policy.py`)
  return JSON.parse(result[0].text)
}
```

#### 3. PUT `/api/agents/{id}/policy`
- **File:** `src/components/PolicyEditorPane.svelte:61`
- **Current:** Direct `fetch()` call with PUT
- **MCP Equivalent:** `set_policy` tool
- **Status:** MCP function already exists in `api.ts` as `setPolicy()`, but component bypasses it
- **Action Required:** Update component to use `setPolicy()` from api.ts

```typescript
// Current (line 61):
const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/policy`
const res = await fetch(url, {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: editingPolicy })
})

// Should be:
import { setPolicy } from '../features/agents/api'
await setPolicy(agentId, editingPolicy)
```

#### 4. POST `/api/agents/{id}/policy/proposals/{id}/approve`
- **File:** `src/components/PolicyEditorPane.svelte:87`
- **Current:** Direct `fetch()` call with POST
- **MCP Equivalent:** `approve_proposal` tool (confirmed in plan.md)
- **Status:** ⚠️ NOT YET in api.ts
- **Action Required:**
  1. Add `approveProposal(agentId, proposalId)` function to api.ts using MCP tool
  2. Update component to use new function

```typescript
// Current (line 87):
const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/policy/proposals/${encodeURIComponent(proposalId)}/approve`
const res = await fetch(url, { method: 'POST' })

// Should add to api.ts:
export async function approveProposal(agentId: string, proposalId: string): Promise<{ok: boolean}> {
  const client = await getMCPClient()
  await callTool(client, 'approve_proposal', {
    agent_id: agentId,
    proposal_id: proposalId
  })
  return { ok: true }
}
```

#### 5. POST `/api/agents/{id}/policy/proposals/{id}/reject`
- **File:** `src/components/PolicyEditorPane.svelte:107`
- **Current:** Direct `fetch()` call with POST
- **MCP Equivalent:** `reject_proposal` tool
- **Status:** MCP function already exists in `api.ts` as `rejectProposal()`, but component bypasses it
- **Action Required:** Update component to use `rejectProposal()` from api.ts

```typescript
// Current (line 107):
const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/policy/proposals/${encodeURIComponent(proposalId)}/reject`
const res = await fetch(url, { method: 'POST' })

// Should be:
import { rejectProposal } from '../features/agents/api'
await rejectProposal(agentId, proposalId)
```

---

### ⚠️ PARTIALLY IMPLEMENTED (1 endpoint)

#### 6. POST `/api/agents/{id}/proposals/{id}/withdraw`
- **File:** `src/features/agents/api.ts:188`
- **Current:** Direct `fetch()` call with fallback comment
- **MCP Equivalent:** `withdraw_proposal` tool (**AGENT-ONLY** per plan.md line 111)
- **Status:** Has MCP equivalent but marked as AGENT-ONLY - not for human UI
- **Action Required:** ⚠️ CLARIFICATION NEEDED
  - Plan.md marks this as "AGENT-ONLY" (line 111)
  - But it's used in `stores_channels.ts:346` by human UI
  - **Question:** Should humans be allowed to withdraw proposals, or is this agent-only?

```typescript
// Current (line 188):
export async function withdrawProposal(agentId: string, proposalId: string): Promise<{ ok: boolean; error?: string | null }> {
  // Withdraw not yet implemented in MCP - fall back to HTTP
  const url = `${backendOrigin()}/api/agents/${encodeURIComponent(agentId)}/proposals/${encodeURIComponent(proposalId)}/withdraw`
  const res = await fetch(url, { method: 'POST' })
  // ...
}

// If humans SHOULD withdraw, update to:
export async function withdrawProposal(agentId: string, proposalId: string): Promise<{ ok: boolean; error?: string | null }> {
  const client = await getMCPClient()
  await callTool(client, 'withdraw_proposal', {
    agent_id: agentId,
    proposal_id: proposalId
  })
  return { ok: true }
}
```

---

### ⏸️ DEFERRED (1 endpoint)

#### 7. POST `/api/agents/{id}/message`
- **File:** `src/components/MessageComposer.svelte:20`
- **Current:** Direct `fetch()` call with POST
- **MCP Equivalent:** `send_message` tool (per plan.md)
- **Status:** ⏸️ OUT OF SCOPE for Phase 1-5 (plan.md line 410)
- **Action Required:** None for now - wait for UI server integration

```typescript
// Current (line 20):
const url = `${origin}/api/agents/${encodeURIComponent(agentId)}/message`
const res = await fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ content: message })
})

// Future migration (when UI server is ready):
export async function sendMessage(agentId: string, content: string): Promise<{ok: boolean}> {
  const client = await getMCPClient()
  await callTool(client, 'send_message', {
    agent_id: agentId,
    content: content
  })
  return { ok: true }
}
```

---

### ✅ OK TO KEEP (2 endpoints)

These are explicitly listed in plan.md as "Keep as HTTP" (lines 127-129):

#### 8. GET `/api/capabilities`
- **File:** `src/features/agents/api.ts:26`
- **Purpose:** Bootstrap handshake helper
- **Status:** ✅ OK to keep as HTTP (per plan.md line 134)

#### 9. GET `/api/presets`
- **File:** `src/features/agents/api.ts:63`
- **Purpose:** Internal server config discovery
- **Status:** ✅ OK to keep as HTTP (per plan.md line 129)

---

## WebSocket Connections

### 🔴 ALL NEED MIGRATION (6 channels)

Per plan.md lines 114-122: "DELETE WebSocket Channels (Replace with MCP Subscriptions)"

#### 1. `/ws/approvals?agent_id={id}`
- **File:** `src/components/ApprovalTimeline.svelte:54`
- **Current:** Direct WebSocket connection for live updates
- **MCP Equivalent:** Subscribe to `resource://agents/{id}/approvals/pending`
- **Action Required:** Replace WebSocket with MCP subscription using `client.subscribe()`

```typescript
// Current (line 54):
const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const wsUrl = `${protocol}//${window.location.host}/ws/approvals?agent_id=${encodeURIComponent(agentId)}`
ws = new WebSocket(wsUrl)
ws.onmessage = (event) => { /* handle updates */ }

// Should be:
const client = await getMCPClient()
await client.subscribe(`resource://agents/${agentId}/approvals/pending`, (notification) => {
  // Handle resource_updated notifications
  if (notification.method === 'notifications/resources/updated') {
    // Refresh approval data
  }
})
```

#### 2. `/ws/agents`
- **File:** `src/features/agents/stores.ts:81`
- **Current:** WebSocket for agent list updates
- **MCP Equivalent:** Subscribe to `resource://agents/list`
- **Action Required:** Replace WebSocket with MCP subscription

#### 3. `/ws/session` (via ChannelManager)
- **File:** `src/features/chat/stores_channels.ts:5,126`
- **Current:** WebSocket channel for agent execution state
- **MCP Equivalent:** Subscribe to `resource://agents/{id}/state`
- **Action Required:** Replace with MCP subscription

#### 4. `/ws/mcp` (via ChannelManager)
- **File:** `src/features/chat/stores_channels.ts:6,129`
- **Current:** WebSocket channel for MCP server state
- **MCP Equivalent:** Subscribe to `resource://agents/{id}/mcp/state`
- **Action Required:** Replace with MCP subscription

#### 5. `/ws/approvals` (via ChannelManager)
- **File:** `src/features/chat/stores_channels.ts:7,136`
- **Current:** WebSocket channel for approval requests
- **MCP Equivalent:** Subscribe to `resource://agents/{id}/approvals/pending`
- **Action Required:** Replace with MCP subscription (same as #1 above)

#### 6. `/ws/policy` (via ChannelManager)
- **File:** `src/features/chat/stores_channels.ts:8,138`
- **Current:** WebSocket channel for policy content
- **MCP Equivalent:** Subscribe to `resource://approval-policy/proposals`
- **Action Required:** Replace with MCP subscription

#### 7. `/ws/ui` (via ChannelManager)
- **File:** `src/features/chat/stores_channels.ts:9,141`
- **Current:** WebSocket channel for UI state (marked optional)
- **MCP Equivalent:** Subscribe to `resource://ui/{id}/blocks`
- **Action Required:** Replace with MCP subscription

**Important Note from plan.md (lines 69-76):**
> **IMPORTANT - Definition of Done for WebSocket Migration**:
> - Post-migration, there should be **ZERO WebSocket endpoints** on the backend
> - Current WebSocket channels are **NOT MCP protocol** - they are still WebSockets
> - These must be replaced with MCP resource subscriptions (listening to `resource_updated` notifications)
> - **Remove channel bundles entirely** - no "channel.bundle" or "_channel_bundle" should exist in repo post-migration

---

## Migration Priorities

### Phase 1: Quick Wins (Components using existing MCP functions)
These components already have MCP equivalents in api.ts but bypass them:
1. ✅ ApprovalTimeline.svelte:29 → use `getApprovalHistory()`
2. ✅ PolicyEditorPane.svelte:61 → use `setPolicy()`
3. ✅ PolicyEditorPane.svelte:107 → use `rejectProposal()`

### Phase 2: Add Missing MCP Functions
Add these functions to api.ts:
1. 🔧 `getPolicy(agentId)` → for PolicyEditorPane.svelte:39
2. 🔧 `approveProposal(agentId, proposalId)` → for PolicyEditorPane.svelte:87
3. ⚠️ Clarify `withdrawProposal()` - agent-only or human-allowed?

### Phase 3: WebSocket Migration (Major)
This is a **future wave** (plan.md line 76) requiring:
1. Reliable MCP subscription infrastructure
2. Replace all 6 WebSocket channels with MCP subscriptions
3. Remove ChannelManager and channel bundle code entirely
4. Update backend to stop serving `/ws/*` endpoints

### Phase 4: Deferred (Post Phase 1-5)
1. ⏸️ MessageComposer.svelte → `send_message` tool (wait for UI server)

---

## Files Affected

### Components with direct HTTP/WS (need updates):
- `/home/user/ducktape/adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte`
- `/home/user/ducktape/adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte`
- `/home/user/ducktape/adgn/src/adgn/agent/web/src/components/MessageComposer.svelte` (deferred)

### Store/API files:
- `/home/user/ducktape/adgn/src/adgn/agent/web/src/features/agents/api.ts` (add 2 functions, clarify 1)
- `/home/user/ducktape/adgn/src/adgn/agent/web/src/features/agents/stores.ts` (WS migration)
- `/home/user/ducktape/adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts` (WS migration)
- `/home/user/ducktape/adgn/src/adgn/agent/web/src/features/chat/channels.ts` (WS infrastructure - delete in Phase 3)

---

## Test Files Affected

These test files reference HTTP/WebSocket endpoints and will need updates:
- `/home/user/ducktape/adgn/src/adgn/agent/web/src/components/ApprovalTimeline.test.ts`
  - Lines 648, 657: Mock fetch for `/api/agents/{id}/approvals/history`
  - Lines 542, 571, 600, 676: Mock WebSocket for `/ws/approvals`

---

## Verification Checklist

After migration, verify:
- [ ] Zero `fetch()` calls to `/api/agents/*` (except deferred endpoints)
- [ ] Zero `new WebSocket()` calls to `/ws/*` endpoints
- [ ] All components use functions from `api.ts`
- [ ] All `api.ts` functions use MCP client (`getMCPClient()`, `callTool()`, `readResource()`)
- [ ] No "channel.bundle" or "_channel_bundle" references remain
- [ ] Backend serves only: static files, `/health`, `/api/presets`, `/api/capabilities`, `/mcp`
- [ ] All tests updated to mock MCP client instead of HTTP/WebSocket

---

## Questions for Clarification

1. **withdrawProposal()**: Plan.md marks `withdraw_proposal` as "AGENT-ONLY" (line 111), but `stores_channels.ts:346` uses it in human UI. Should humans be allowed to withdraw proposals?

2. **approve_proposal tool**: Plan.md line 109 says it exists, but it's not yet in api.ts. Confirm the tool name is `approve_proposal` (not `approve_policy_proposal` or similar).

3. **Phase 3 timing**: When should WebSocket → MCP subscription migration happen? Plan.md says it's a "future wave" - is there a target wave number?

---

**End of Audit**
