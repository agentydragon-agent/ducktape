# Frontend HTTP Endpoint Audit

**Date**: 2025-11-19
**Scope**: `/home/user/ducktape/adgn/src/adgn/agent/web/src/`
**Purpose**: Identify all HTTP/WebSocket endpoints for Wave D migration to MCP

---

## Executive Summary

### Migration Status
- ✅ **Already Migrated to MCP**: Agent management (create, delete, list, status), MCP server attachment, most approvals/policy operations, agent control (abort, prompt)
- 🔄 **HTTP Endpoints Still in Use**: 9 endpoints (bootstrap capabilities, presets, policy operations, message sending, proposal withdrawal, approval history)
- 🔄 **WebSocket Endpoints Still in Use**: 6 channels (agents, session, mcp, approvals, policy, ui)
- 📊 **Total Source Files Analyzed**: 47 TypeScript/Svelte files

### Quick Stats
- **HTTP REST Endpoints**: 9 active (5 GET, 3 POST, 1 PUT)
- **WebSocket Channels**: 6 active
- **MCP Tools in Use**: 13+ tools
- **MCP Resources in Use**: 6+ resources

---

## 1. HTTP REST Endpoints (Still in Use)

### 1.1 Bootstrap & Configuration

#### GET `/api/capabilities`
- **File**: `adgn/src/adgn/agent/web/src/features/agents/api.ts:26`
- **Purpose**: Server capabilities detection (mode: full_agent vs mcp_bridge)
- **Data Sent**: None
- **Data Received**:
  ```typescript
  {
    mode: 'full_agent' | 'mcp_bridge',
    components: {
      mcp: boolean,
      approvals: boolean,
      chat: boolean,
      agent_state: boolean,
      ui: boolean
    }
  }
  ```
- **Operation**: READ (GET)
- **Used By**: Server capabilities loading on startup
- **Notes**: Kept as HTTP for bootstrap before MCP connection established

#### GET `/api/presets`
- **File**: `adgn/src/adgn/agent/web/src/features/agents/api.ts:63`
- **Purpose**: List available agent presets
- **Data Sent**: None
- **Data Received**: `{ presets: Array<{ name: string, description?: string }> }`
- **Operation**: READ (GET)
- **Used By**: Agent creation UI
- **Notes**: Not yet migrated to MCP

---

### 1.2 Policy Management

#### GET `/api/agents/{agentId}/policy`
- **File**: `adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte:39-40`
- **Purpose**: Fetch current approval policy
- **Data Sent**: None (agent ID in URL)
- **Data Received**: `ApprovalPolicyInfo` (policy content, version, proposals)
- **Operation**: READ (GET)
- **Used By**: PolicyEditorPane component
- **Notes**: Should migrate to MCP resource

#### PUT `/api/agents/{agentId}/policy`
- **File**: `adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte:61-66`
- **Purpose**: Update approval policy
- **Data Sent**: `{ content: string }` (policy code)
- **Data Received**: Success response
- **Operation**: WRITE (PUT)
- **Used By**: PolicyEditorPane save button
- **Notes**: Already has MCP equivalent (`set_policy` tool) but not used in this component

#### POST `/api/agents/{agentId}/policy/proposals/{proposalId}/approve`
- **File**: `adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte:87-88`
- **Purpose**: Approve a policy proposal
- **Data Sent**: None (IDs in URL)
- **Data Received**: Success response
- **Operation**: WRITE (POST)
- **Used By**: PolicyEditorPane proposal approval
- **Notes**: Could use MCP `set_policy` tool with proposal_id

#### POST `/api/agents/{agentId}/policy/proposals/{proposalId}/reject`
- **File**: `adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte:107-108`
- **Purpose**: Reject a policy proposal
- **Data Sent**: None (IDs in URL)
- **Data Received**: Success response
- **Operation**: WRITE (POST)
- **Used By**: PolicyEditorPane proposal rejection
- **Notes**: Has MCP equivalent (`reject_proposal` tool)

---

### 1.3 Approvals & History

#### GET `/api/agents/{agentId}/approvals/history`
- **File**: `adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte:29-30`
- **Purpose**: Fetch approval history timeline
- **Data Sent**: None (agent ID in URL)
- **Data Received**: `{ timeline: ApprovalHistoryEntry[] }`
- **Operation**: READ (GET)
- **Used By**: ApprovalTimeline component initial load
- **Notes**: Should migrate to MCP resource (currently uses HTTP + WebSocket combo)

---

### 1.4 Agent Communication

#### POST `/api/agents/{agentId}/message`
- **File**: `adgn/src/adgn/agent/web/src/components/MessageComposer.svelte:20-25`
- **Purpose**: Send message to agent
- **Data Sent**: `{ content: string }` (user message)
- **Data Received**: Success response
- **Operation**: WRITE (POST)
- **Used By**: MessageComposer send button
- **Notes**: Has MCP equivalent (`prompt` tool) but not used in this component

---

### 1.5 Proposal Management

#### POST `/api/agents/{agentId}/proposals/{proposalId}/withdraw`
- **File**: `adgn/src/adgn/agent/web/src/features/agents/api.ts:188-189`
- **Purpose**: Withdraw a proposal
- **Data Sent**: None (IDs in URL)
- **Data Received**: `{ ok: boolean, error?: string }`
- **Operation**: WRITE (POST)
- **Used By**: `withdrawProposal()` function in API layer
- **Notes**: Marked as "not yet implemented in MCP" in comments

---

## 2. WebSocket Endpoints (Still in Use)

### 2.1 Global Agents WebSocket

#### WS `/ws/agents`
- **File**: `adgn/src/adgn/agent/web/src/features/agents/stores.ts:81`
- **Purpose**: Real-time agent list and status updates
- **Message Types**:
  - `agents_snapshot`: Initial agent list
  - `agent_created`: New agent added
  - `agent_deleted`: Agent removed
  - `agent_status`: Agent status update (live, working, lifecycle, etc.)
- **Data Flow**: Server → Client (broadcast)
- **Used By**: AgentsSidebar for real-time agent list
- **Notes**: Replaces HTTP polling for `/api/agents`

---

### 2.2 Per-Agent WebSocket Channels

The frontend uses a modular channel architecture with separate WebSocket connections per feature:

#### WS `/ws/session?agent_id={agentId}`
- **File**: `adgn/src/adgn/agent/web/src/features/chat/channels.ts:44`
- **Purpose**: Agent execution state and transcript
- **Message Types**:
  - `session_snapshot`: Initial session/run state
  - `user_text`: User message
  - `assistant_text`: Assistant response
  - `tool_call`: Tool invocation
  - `tool_result`: Tool execution result
  - `reasoning`: Agent reasoning
  - `run_status`: Run state change
  - `turn_done`: Turn completion
- **Data Flow**: Bidirectional
- **Used By**: ChatPane for transcript display
- **Notes**: Core conversation channel

#### WS `/ws/mcp?agent_id={agentId}`
- **File**: `adgn/src/adgn/agent/web/src/features/chat/channels.ts:44`
- **Purpose**: MCP server state
- **Message Types**:
  - `mcp_snapshot`: Initial MCP servers list
  - `mcp_server_attached`: Server added
  - `mcp_server_detached`: Server removed
- **Data Flow**: Server → Client
- **Used By**: ServersPanel for MCP server status
- **Notes**: Live MCP configuration updates

#### WS `/ws/approvals?agent_id={agentId}`
- **File**: `adgn/src/adgn/agent/web/src/features/chat/channels.ts:44`
- **Purpose**: Approval requests and decisions
- **Message Types**:
  - `approvals_snapshot`: Initial pending approvals
  - `approval_pending`: New approval request
  - `approval_decision`: Approval decided
- **Data Flow**: Bidirectional
- **Used By**: ApprovalsPanel, ApprovalTimeline
- **Notes**: Real-time approval workflow

#### WS `/ws/policy?agent_id={agentId}`
- **File**: `adgn/src/adgn/agent/web/src/features/chat/channels.ts:44`
- **Purpose**: Policy content updates
- **Message Types**:
  - `policy_snapshot`: Current policy
  - `policy_updated`: Policy version changed
  - `policy_proposal`: New proposal created
- **Data Flow**: Server → Client
- **Used By**: PolicyEditorPane
- **Notes**: Live policy updates

#### WS `/ws/ui?agent_id={agentId}`
- **File**: `adgn/src/adgn/agent/web/src/features/chat/channels.ts:44`
- **Purpose**: UI state synchronization (optional)
- **Message Types**:
  - `ui_state_snapshot`: Initial UI state
  - `ui_state_updated`: UI state changed
  - `ui_message`: UI-specific message
  - `ui_end_turn`: Turn end marker
- **Data Flow**: Server → Client
- **Used By**: ChatPane UI state
- **Notes**: Marked as optional channel (graceful degradation)

---

## 3. MCP Usage (Already Migrated)

### 3.1 MCP Client Configuration

**Primary Endpoint**: `GET /mcp` (StreamableHTTP transport)
**Authentication**: Bearer token from URL params or localStorage
**Client Manager**: `adgn/src/adgn/agent/web/src/features/mcp/clientManager.ts`

### 3.2 MCP Tools in Use

#### Agent Management Tools
- ✅ **`create_agent`** - Create new agent from preset
  - **File**: `api.ts:73`
  - **Params**: `{ preset: string, system_message?: string }`
  - **Returns**: `{ agent_id: string }`

- ✅ **`delete_agent`** - Delete agent
  - **File**: `api.ts:97`
  - **Params**: `{ agent_id: string }`
  - **Returns**: Success

- ✅ **`abort_agent`** - Abort agent run
  - **File**: `ChatPane.svelte:116`
  - **Params**: `{ agent_id: string }`
  - **Returns**: Success

#### MCP Server Management Tools
- ✅ **`attach_server`** - Attach MCP server to agent
  - **File**: `api.ts:136`
  - **Params**: `{ agent_id: string, name: string, spec: any }`
  - **Returns**: Success

- ✅ **`detach_server`** - Detach MCP server from agent
  - **File**: `api.ts:155`
  - **Params**: `{ agent_id: string, name: string }`
  - **Returns**: Success

#### Approval Tools
- ✅ **`approve_tool_call`** - Approve a tool call
  - **File**: `api.ts:268`, `GlobalApprovalsList.svelte:143`
  - **Params**: `{ agent_id: string, call_id: string }`
  - **Returns**: Success

- ✅ **`reject_tool_call`** - Reject a tool call
  - **File**: `GlobalApprovalsList.svelte:178`
  - **Params**: `{ agent_id: string, call_id: string, reason: string }`
  - **Returns**: Success

- ✅ **`deny_tool_call`** - Deny and continue
  - **File**: `api.ts:289`
  - **Params**: `{ agent_id: string, call_id: string, reason: string }`
  - **Returns**: Success

- ✅ **`deny_abort`** - Deny and abort
  - **File**: `api.ts:311`
  - **Params**: `{ agent_id: string, call_id: string, reason: string }`
  - **Returns**: Success

#### Policy Tools
- ✅ **`set_policy`** - Update policy
  - **File**: `api.ts:200`
  - **Params**: `{ agent_id: string, policy_text: string }`
  - **Returns**: Success

- ✅ **`reject_proposal`** - Reject policy proposal
  - **File**: `api.ts:221`
  - **Params**: `{ agent_id: string, proposal_id: string, reason: string }`
  - **Returns**: Success

#### Agent Control Tools
- ✅ **`prompt`** - Send prompt to agent
  - **File**: `api.ts:333`
  - **Params**: `{ agent_id: string, message: string }`
  - **Returns**: Success

- ✅ **`abort_run`** - Abort current run
  - **File**: `api.ts:354`
  - **Params**: `{ agent_id: string }`
  - **Returns**: Success

---

### 3.3 MCP Resources in Use

#### Agent Resources
- ✅ **`resource://agents/list`** - List all agents
  - **File**: `api.ts:34`, `AgentsSidebar.svelte:56`
  - **Returns**: `{ agents: Array<{ agent_id: string, ... }> }`

- ✅ **`resource://agents/{id}/info`** - Agent status
  - **File**: `api.ts:113`
  - **Returns**: `{ agent_id: string, status: string, ... }`

- ✅ **`resource://agents/{id}/snapshot`** - Agent snapshot
  - **File**: `api.ts:175`
  - **Returns**: Full agent state snapshot

- ✅ **`resource://agents/{id}/policy/proposals`** - Policy proposals
  - **File**: `api.ts:241`
  - **Returns**: `{ proposals: Array<{ id: string, ... }> }`

- ✅ **`resource://agents/{id}/approvals/history`** - Approval history
  - **File**: `api.ts:372`
  - **Returns**: `{ history: Array<{ ... }> }`

#### Global Resources
- ✅ **`resource://approvals/pending`** - Global pending approvals
  - **File**: `GlobalApprovalsList.svelte:102`
  - **Returns**: Multiple TextResourceContents blocks with approval JSON
  - **Notes**: Used by GlobalApprovalsList component (currently shows error - endpoint not exposed)

---

### 3.4 MCP Subscriptions

The MCP client supports resource subscriptions for live updates:

- ✅ **`resource://agents/list`** - Subscribe to agent list changes
  - **File**: `AgentsSidebar.svelte:98`

- ✅ **`resource://approvals/pending`** - Subscribe to global approvals
  - **File**: `GlobalApprovalsList.svelte:67`
  - **Notes**: Fallback to 5s polling if subscription not supported

---

## 4. Migration Categorization by Feature

### 4.1 ✅ Fully Migrated to MCP (No HTTP/WS needed)

- Agent CRUD operations (create, delete, list)
- Agent status queries
- MCP server attachment/detachment
- Approval decisions (approve, deny, reject)
- Policy updates (set_policy, reject_proposal)
- Agent control (abort, prompt)

---

### 4.2 🔄 Hybrid (HTTP + MCP available, both in use)

#### Policy Management
- **Current**: PolicyEditorPane uses HTTP endpoints
- **MCP Available**: `set_policy`, `reject_proposal` tools exist
- **Migration Path**: Replace HTTP calls in PolicyEditorPane.svelte with MCP tool calls
- **Files to Update**:
  - `PolicyEditorPane.svelte:39-46` (GET policy → MCP resource)
  - `PolicyEditorPane.svelte:61-66` (PUT policy → `set_policy` tool)
  - `PolicyEditorPane.svelte:87-95` (approve → `set_policy` with proposal_id)
  - `PolicyEditorPane.svelte:107-115` (reject → `reject_proposal` tool)

#### Agent Messaging
- **Current**: MessageComposer uses HTTP POST
- **MCP Available**: `prompt` tool exists
- **Migration Path**: Replace HTTP call with MCP tool
- **Files to Update**:
  - `MessageComposer.svelte:20-25` (POST message → `prompt` tool)

---

### 4.3 🔴 HTTP-Only (No MCP equivalent yet)

#### Bootstrap & Configuration
- **`GET /api/capabilities`** - Server mode detection
  - **Reason**: Needs to run before MCP connection established
  - **Migration**: Keep as HTTP (bootstrap endpoint)

- **`GET /api/presets`** - List agent presets
  - **Migration**: Create MCP resource `resource://presets/list`

#### Proposal Management
- **`POST /api/agents/{id}/proposals/{id}/withdraw`** - Withdraw proposal
  - **Migration**: Create MCP tool `withdraw_proposal`
  - **Note**: Explicitly marked as "not yet implemented in MCP" in `api.ts:187`

#### Approval History
- **`GET /api/agents/{id}/approvals/history`** - Fetch history
  - **Migration**: Already has MCP resource `resource://agents/{id}/approvals/history` (api.ts:372)
  - **Files to Update**:
    - `ApprovalTimeline.svelte:29-30` (use MCP resource instead of HTTP)

---

### 4.4 🔴 WebSocket Channels (No MCP subscription equivalent)

All WebSocket channels are still required because:
1. MCP subscriptions don't support the rich event streaming needed
2. Transcript items (session channel) have no MCP equivalent
3. Real-time UI updates require low-latency WebSocket

**Keep all 6 WebSocket channels**:
- `/ws/agents` - Global agent list/status
- `/ws/session` - Agent transcript/execution
- `/ws/mcp` - MCP server state
- `/ws/approvals` - Approval workflow
- `/ws/policy` - Policy updates
- `/ws/ui` - UI state sync

---

## 5. Wave D Migration Recommendations

### 5.1 High Priority (Easy Wins)

1. **PolicyEditorPane Component**
   - Replace 4 HTTP calls with existing MCP tools/resources
   - Estimated effort: 2-4 hours
   - Files: `PolicyEditorPane.svelte`

2. **MessageComposer Component**
   - Replace 1 HTTP call with existing `prompt` tool
   - Estimated effort: 1 hour
   - Files: `MessageComposer.svelte`

3. **ApprovalTimeline Component**
   - Replace 1 HTTP call with existing MCP resource
   - Estimated effort: 1 hour
   - Files: `ApprovalTimeline.svelte`

### 5.2 Medium Priority (New MCP Features)

4. **Agent Presets**
   - Create MCP resource `resource://presets/list`
   - Update `listPresets()` to use MCP
   - Estimated effort: 3-4 hours
   - Files: `api.ts:61-65`

5. **Proposal Withdrawal**
   - Create MCP tool `withdraw_proposal`
   - Update `withdrawProposal()` to use MCP
   - Estimated effort: 2-3 hours
   - Files: `api.ts:186-192`

### 5.3 Low Priority (Keep as HTTP)

6. **Server Capabilities**
   - Keep as HTTP bootstrap endpoint
   - No migration needed
   - Reason: Must run before MCP connection

### 5.4 Out of Scope (Keep as WebSocket)

7. **All WebSocket Channels**
   - Keep current implementation
   - Reason: MCP doesn't provide equivalent real-time streaming
   - Consider: Future MCP extension for event streaming

---

## 6. Implementation Checklist

### Phase 1: Quick Wins (1 week)
- [ ] Migrate PolicyEditorPane to MCP tools/resources
- [ ] Migrate MessageComposer to `prompt` tool
- [ ] Migrate ApprovalTimeline to MCP resource
- [ ] Test all migrated components
- [ ] Update documentation

### Phase 2: New Features (1 week)
- [ ] Implement `resource://presets/list` on backend
- [ ] Migrate listPresets() to MCP resource
- [ ] Implement `withdraw_proposal` tool on backend
- [ ] Migrate withdrawProposal() to MCP tool
- [ ] Test all new features
- [ ] Update API documentation

### Phase 3: Cleanup (2-3 days)
- [ ] Remove unused HTTP endpoint handlers
- [ ] Update API types/interfaces
- [ ] Clean up deprecated code paths
- [ ] Final integration testing
- [ ] Update architecture documentation

---

## 7. Risk Assessment

### Low Risk
- ✅ PolicyEditorPane migration (MCP tools already exist)
- ✅ MessageComposer migration (MCP tool already exists)
- ✅ ApprovalTimeline migration (MCP resource already exists)

### Medium Risk
- ⚠️ Presets migration (new MCP resource needed)
- ⚠️ Proposal withdrawal (new MCP tool needed)

### No Risk (Keep as-is)
- 🟢 Server capabilities endpoint (HTTP bootstrap)
- 🟢 All WebSocket channels (no MCP equivalent)

---

## 8. Files Requiring Updates

### Frontend Files (8 files)
1. `adgn/src/adgn/agent/web/src/components/PolicyEditorPane.svelte` - 4 endpoints → MCP
2. `adgn/src/adgn/agent/web/src/components/MessageComposer.svelte` - 1 endpoint → MCP
3. `adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte` - 1 endpoint → MCP
4. `adgn/src/adgn/agent/web/src/features/agents/api.ts` - Update 3 functions
5. `adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte` - Already MCP (fix endpoint exposure)

### Backend Files (estimated, requires backend audit)
- MCP resource handler for presets
- MCP tool handler for withdraw_proposal
- Remove deprecated HTTP handlers (after frontend migration complete)

---

## 9. Testing Strategy

### Unit Tests
- Test each migrated component in isolation
- Mock MCP client responses
- Verify error handling

### Integration Tests
- Test full flows (create agent → send message → approve tools)
- Test MCP connection failures (graceful degradation)
- Test WebSocket fallback behavior

### E2E Tests
- Test critical user journeys
- Verify real-time updates still work
- Test error recovery

---

## 10. Rollback Plan

1. **Feature Flags**: Add flags to toggle MCP vs HTTP per feature
2. **Incremental Migration**: Deploy one component at a time
3. **Monitoring**: Track MCP call success rates
4. **Quick Revert**: Keep HTTP handlers for 2 releases after migration
5. **Documentation**: Maintain migration log for debugging

---

## Appendix A: Complete Endpoint Index

### HTTP Endpoints (9 total)
1. `GET /api/capabilities` - Server capabilities
2. `GET /api/presets` - List presets
3. `GET /api/agents/{id}/policy` - Fetch policy
4. `PUT /api/agents/{id}/policy` - Update policy
5. `POST /api/agents/{id}/policy/proposals/{id}/approve` - Approve proposal
6. `POST /api/agents/{id}/policy/proposals/{id}/reject` - Reject proposal
7. `GET /api/agents/{id}/approvals/history` - Approval history
8. `POST /api/agents/{id}/message` - Send message
9. `POST /api/agents/{id}/proposals/{id}/withdraw` - Withdraw proposal

### WebSocket Channels (6 total)
1. `WS /ws/agents` - Agent list/status
2. `WS /ws/session?agent_id={id}` - Session/transcript
3. `WS /ws/mcp?agent_id={id}` - MCP servers
4. `WS /ws/approvals?agent_id={id}` - Approvals
5. `WS /ws/policy?agent_id={id}` - Policy
6. `WS /ws/ui?agent_id={id}` - UI state (optional)

### MCP Tools (13 total)
1. `create_agent` - Create agent
2. `delete_agent` - Delete agent
3. `abort_agent` - Abort agent
4. `attach_server` - Attach MCP server
5. `detach_server` - Detach MCP server
6. `approve_tool_call` - Approve tool call
7. `reject_tool_call` - Reject tool call
8. `deny_tool_call` - Deny and continue
9. `deny_abort` - Deny and abort
10. `set_policy` - Update policy
11. `reject_proposal` - Reject policy proposal
12. `prompt` - Send prompt
13. `abort_run` - Abort run

### MCP Resources (6 total)
1. `resource://agents/list` - Agent list
2. `resource://agents/{id}/info` - Agent info
3. `resource://agents/{id}/snapshot` - Agent snapshot
4. `resource://agents/{id}/policy/proposals` - Policy proposals
5. `resource://agents/{id}/approvals/history` - Approval history
6. `resource://approvals/pending` - Global pending approvals

---

## Appendix B: Component Dependency Graph

```
AgentsSidebar
├── MCP resource: resource://agents/list
└── WS channel: /ws/agents

ChatPane
├── MCP tool: abort_agent
├── MCP resource: resource://agents/list (for mode detection)
└── WS channel: /ws/session

PolicyEditorPane (NEEDS MIGRATION)
├── HTTP GET: /api/agents/{id}/policy
├── HTTP PUT: /api/agents/{id}/policy
├── HTTP POST: /api/agents/{id}/policy/proposals/{id}/approve
├── HTTP POST: /api/agents/{id}/policy/proposals/{id}/reject
└── (MCP equivalents exist: set_policy, reject_proposal)

MessageComposer (NEEDS MIGRATION)
├── HTTP POST: /api/agents/{id}/message
└── (MCP equivalent exists: prompt)

ApprovalTimeline (NEEDS MIGRATION)
├── HTTP GET: /api/agents/{id}/approvals/history
├── WS channel: /ws/approvals
└── (MCP equivalent exists: resource://agents/{id}/approvals/history)

ApprovalsPanel
├── MCP tools: approve_tool_call, deny_tool_call, deny_abort
└── WS channel: /ws/approvals

GlobalApprovalsList
├── MCP resource: resource://approvals/pending
└── MCP tools: approve_tool_call, reject_tool_call

ServersPanel
├── MCP tools: attach_server, detach_server
└── WS channel: /ws/mcp
```

---

**Report End**
