# MCP-Based Management UI - Remaining Work

**Status**: Infrastructure complete (Waves A-I done). Active cleanup and migration tasks remaining.

**Reference**: Actual implementation in `adgn/src/adgn/agent/mcp_bridge/`, `adgn/src/adgn/agent/web/src/`, `adgn/tests/agent/mcp_bridge/`.

---

## Priority Tasks

### Wave 1: Code Quality Fixes (IMMEDIATE)

**Estimated Time**: 1-2 hours

#### 1.1 Fix Ruff Violations (41 remaining)
```bash
cd adgn
uv run ruff check src/adgn/agent tests/agent --fix
uv run ruff check src/adgn/agent tests/agent --fix --unsafe-fixes
```

**Known issues**:
- I001: Import block sorting (1+ occurrences)
- PT011: `pytest.raises(Exception)` too broad (4 occurrences)
- F841: Unused local variables
- Other fixable violations

#### 1.2 Fix Mypy Type Errors (if present)
```bash
cd adgn
uv run python -m mypy src/adgn/agent
```

**Potential issues** (from WAVE_EXECUTION_PLAN.md):
- `src/adgn/agent/persist/sqlite.py:355,382` - ProposalStatus string conversion
- `src/adgn/agent/mcp_bridge/servers/agents.py:520,730` - Type mismatches
- Other type errors in reducer.py, runtime.py, agent.py

#### 1.3 Fix Test Failures
```bash
cd adgn
.venv/bin/pytest tests/agent -q -m "not live_llm"
```

**Known issues** (from WAVE_EXECUTION_PLAN.md):
- Test failures related to WebSocket/HTTP endpoint removal
- Import errors from deleted modules
- Tests need updating to use MCP-based APIs

---

### Wave 2: WebSocket Migration to MCP (HIGH PRIORITY)

**Estimated Time**: 3-4 hours

#### 2.1 Migrate `/ws/session` to MCP
**Status**: ❌ **NOT MIGRATED** - WebSocket still in use
**File**: `adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts:128`
**Backend**: MCP resource `resource://agents/{id}/session/state` exists and functional

**Tasks**:
1. Remove 'session' channel from ChannelManager
2. Create MCP subscription to `resource://agents/{id}/session/state`
3. Update `handleSessionMessage` to `handleSessionUpdate` (process MCP resource data)
4. Test transcript display, live updates, run status

**Code change**:
```typescript
// In stores_channels.ts
// REMOVE:
manager.on('session', createChannelHandlers('session', handleSessionMessage))

// ADD:
const uri = `resource://agents/${agentId}/session/state`
await subscriptionManager.subscribe(uri, handleSessionUpdate)
```

#### 2.2 Complete `/ws/policy` Migration
**Status**: ⚠️ **PARTIALLY MIGRATED** - Mixed usage
**File**: `adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts:130`
**Backend**: MCP resource `resource://agents/{id}/policy/state` exists and functional

**Current state**:
- PolicyEditorPane component: ✅ Uses MCP subscription
- stores_channels.ts: ❌ Still uses WebSocket channel

**Tasks**:
1. Remove 'policy' channel from ChannelManager in `stores_channels.ts`
2. Update `approvalPolicy` store to use MCP subscription (like PolicyEditorPane)
3. Verify proposal notifications work via MCP
4. Test policy editor, proposals panel

**Testing checklist**:
- [ ] `/ws/session` removed: Transcript updates work via MCP subscription
- [ ] `/ws/policy` removed: Policy editor and proposals work via MCP
- [ ] No WebSocket connections except MCP's `/mcp` endpoint
- [ ] All frontend components using MCP subscriptions for live updates
- [ ] E2E tests pass (test_mcp_ui.py, test_mcp_concurrent.py)

**Note**: `/api/capabilities` HTTP endpoint is intentionally kept for bootstrap (before MCP connection established).

---

## Remaining Work

### Wave 7: UI Layout Implementation

**Current**: UI has left sidebar (agents + approvals tabs) + main ChatPane
**Target**: Side-by-side Agent Timeline + Policy Editor + Message Composer (per UI mockups)

**Components exist but need integration**:
- `ApprovalTimeline.svelte` (27 tests, 557 lines) → **rename to `AgentTimeline.svelte`** (shows all events: approvals, tool calls, UI messages)
- `GlobalApprovalsList.svelte` (19 tests, 15KB) - global mailbox view
- `PolicyEditorPane.svelte` (330 lines) - COMPLETE, needs integration
- `MessageComposer.svelte` (198 lines) - COMPLETE, needs integration
- `ApprovalsPanel.svelte` (3.9KB) - contains policy editor

**Tasks** (8 parallel agents):
1. Rename + enhance ApprovalTimeline → AgentTimeline: merge `UiDisplayItem[]` (UserMessage, AssistantMarkdown, Tool, EndTurn) from `uiState` store
2. Update App.svelte: CSS grid layout (timeline | policy) + conditional composer
3. Wire MCP subscriptions: `resource://agents/{id}/approvals/history`, `resource://approval-policy/policy.py`
4. Detect UI server: check `$agentStatus.ui?.ready`, conditional composer rendering
5. Add agent mode badge: [LOCAL] or [BRIDGE] (indicates agent loop presence)
6. Update routing: global approvals view, agent selection
7. Extract CSS from overlong Svelte files (>500 lines): ApprovalTimeline.svelte at 557 lines
8. Integration testing: Verify timeline updates, policy editing, message sending

---

## Web Frontend Followups

### ApprovalTimeline Component Enhancements (Future)

**Component**: `src/adgn/agent/web/src/components/ApprovalTimeline.svelte`

**Future enhancements**:
- Export timeline to CSV/JSON
- Advanced filtering (by date range, decision method)
- Grouping by tool or time period
- Pagination for very long timelines
- Search in arguments (deep search, not just tool names)
- Statistics/summary view (decision counts, approval rates)
- Keyboard shortcuts for filtering
- Accessibility improvements (ARIA labels)

**Testing needed** (deferred):
- Unit Tests: filtering logic, sorting logic, argument formatting, timestamp formatting
- Integration Tests: API fetch, live updates, error states
- E2E Tests: user filters timeline, searches tools, toggles sort order, expands arguments

### TypeScript Generated Types Integration

**Status**: Generated types file created and verified; shared types actively used throughout codebase.

**Future tasks**:
1. **Update API Layer** (`features/agents/api.ts`)
   - Import generated types from `src/generated/types.ts`
   - Type API responses using generated types

2. **Add Type Guards**
   - Create utilities to validate runtime data matches generated types
   - Use for API responses and resource reads

3. **Update Store Types**
   - Use generated types in Svelte stores where applicable
   - Map between generated and shared types as needed

**Key Type Overlaps** (keep both, map where needed):
- `ApprovalOutcome` (generated, 6 variants) vs `ApprovalKind` (shared, 3 variants)
- `PolicyProposalInfo` (generated, complete) vs `Proposal` (shared, simplified)
- `AgentInfo` (generated, static config) vs `AgentRow`/`AgentStatus` (shared, runtime state)

### GlobalApprovalsList Component

**Component**: `src/adgn/agent/web/src/components/GlobalApprovalsList.svelte`

**Future enhancements**:
- Real-time Subscriptions: Replace polling with resource subscriptions (instant updates)
- Bulk Actions: Multi-select approvals, approve/reject multiple at once
- Filtering and Search: Filter by agent_id, search by tool name, filter by timestamp
- Approval History: Show recently approved/rejected items, undo capability
- Notifications: Browser notifications for new approvals, optional sound alerts

### Component Testing Status

**Blocked Tests**:
- `src/adgn/agent/web/src/components/GlobalApprovalsList.test.ts` (19 tests written)
- `src/adgn/agent/web/src/components/ApprovalTimeline.test.ts` (27 tests written)
- **Blocker**: Svelte 6 + vitest incompatibility (waiting for upstream support)

**Manual Testing Approach** (interim):
- TypeScript compilation validates component interfaces
- E2E tests can verify functionality once vitest support lands

### Pre-existing TypeScript Errors

**Note**: 11 discriminated union property access errors in Svelte components (pre-existing):
- Files: `ServersPanel.svelte`, `RightSidebar.svelte`, `ChatPane.svelte`, etc.
- Issue: Accessing variant-specific properties without type narrowing
- Status: Not blocking; should be addressed separately

---

## Future Work

### Agent State Notifications
- Wire `resource://agents/{id}/state` to emit `resource_updated` on:
  - User prompt, assistant message, tool call, approval decision
- Pattern: compositor/session events → `server.broadcast_resource_updated(resources.agent_state(agent_id))`

### Loop Hooks / DB
- Implement `loop.enable_hook/disable_hook` with `loop://hooks/{id}` resources
- Orchestrator bridge: coalesced notifications → hooks
- Read-only DB MCP server: `db://view/*`, `query`

### Chat / UI Delivery
- Promote MCP-native chat inbox (`ui://chat/inbox`, `chat_read_since`)
- Runtime bridges: human chat notifications → `UiState`, assistant outputs → `chat.assistant.post`

### Documentation
- Update MCP runtime docs after loop hooks + DB server land
- Document chat inbox architecture
- Cross-reference seatbelt TODO in sandboxer/MCP docs

### Misc Cleanups
- Seatbelt: structured findings, remove implicit trace write, CLI shim
- Tests: `_tool_choice_from_policy`, resource-window
- CI: `adgn-trivial-patterns`, split lanes (WT/Docker)
- NotifyingFastMCP: replace private attr overrides if public hooks available
- Policy gateway: document error stamps, add spoofing tests

### Type Hint Migration
Replace `agent_id: str` with `agent_id: AgentID` throughout codebase for type safety:
- AgentID is NewType-based: `AgentID = NewType("AgentID", str)`
- Search pattern: function/method parameters named `agent_id` with type `str`
- Also apply to `call_id`, `proposal_id`, `policy_id` if similar NewTypes exist
- Tool signatures in mcp_bridge/servers/agents.py should use `agent_id: AgentID`

---

## Key Decisions (Historical Context)

### Type Organization
New persistence types (`Decision`, `ToolCallExecution`, `ToolCallRecord`) live in `adgn/src/adgn/agent/persist/__init__.py` alongside `ApprovalRecord`.

### Type Consolidation
Keep two `ToolCall` types:
- Simple `ToolCall` in `approvals.py` - for persistence/approvals
- Discriminated `ToolCall` in `protocol.py` (with `type` field) - for wire protocol

### Policy Proposals UI Access
Frontend directly uses existing policy server resources. No routing through agents server.

### Agents Server Pattern
`agents` server is a FastMCP proxy doing translation/routing to per-agent MCP servers (compositor pattern).

### Database Migration Strategy
Drop and recreate databases (existing approval history will be lost). Acceptable for personal infrastructure during development.

---

## UI Mockups Reference

### Agent WITH UI Server (Local Loop)
```
┌────────────────────────────────────────────────────────────────────┐
│ Agent: agent-1                                [LOCAL] [Agent Loop ✓]│
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────────────────────┐  ┌─────────────────────────────┐│
│  │   TOOL CALL TIMELINE         │  │   POLICY EDITOR             ││
│  │                              │  │                             ││
│  │ ┌──────────────────────────┐ │  │ ```python                   ││
│  │ │✓ exec("ls")              │ │  │ def decide(call):           ││
│  │ │  Auto-approved           │ │  │   if "rm -rf" in call.args: ││
│  │ │  14:23:11                │ │  │     return DENY             ││
│  │ └──────────────────────────┘ │  │   return ALLOW              ││
│  │                              │  │ ```                         ││
│  │ ┌──────────────────────────┐ │  │                             ││
│  │ │⏸️ exec("rm -rf /")        │ │  │ [Save Policy]               ││
│  │ │  PENDING                 │ │  │                             ││
│  │ │  [Approve] [Reject]      │ │  │ Proposals (2 pending)       ││
│  │ └──────────────────────────┘ │  │ • Allow git operations      ││
│  │                              │  │ • Restrict network access   ││
│  │ ┌──────────────────────────┐ │  │ [View All]                  ││
│  │ │💬 [UI Block from UI srv] │ │  │                             ││
│  │ │  "Build completed ✓"     │ │  │                             ││
│  │ │  14:24:05                │ │  │                             ││
│  │ └──────────────────────────┘ │  │                             ││
│  │                              │  │                             ││
│  │ ┌──────────────────────────┐ │  │                             ││
│  │ │✗ curl("evil.com")        │ │  │                             ││
│  │ │  Rejected by policy      │ │  │                             ││
│  │ │  14:25:01                │ │  │                             ││
│  │ └──────────────────────────┘ │  │                             ││
│  │                              │  │                             ││
│  └──────────────────────────────┘  └─────────────────────────────┘│
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ MESSAGE COMPOSER                                             │ │
│  │ ┌──────────────────────────────────────────────────────────┐ │ │
│  │ │ Type a message...                                        │ │ │
│  │ └──────────────────────────────────────────────────────────┘ │ │
│  │                                           [Send] [Abort Agent]│ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

### Agent WITHOUT UI Server (Remote/Bridge)
```
┌────────────────────────────────────────────────────────────────────┐
│ Agent: chatgpt-session-xyz                           [BRIDGE]      │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌──────────────────────────────┐  ┌─────────────────────────────┐│
│  │   TOOL CALL TIMELINE         │  │   POLICY EDITOR             ││
│  │                              │  │                             ││
│  │ ┌──────────────────────────┐ │  │ ```python                   ││
│  │ │✓ read_file("/etc/passwd")│ │  │ def decide(call):           ││
│  │ │  Auto-approved           │ │  │   if "rm -rf" in call.args: ││
│  │ │  14:23:11                │ │  │     return DENY             ││
│  │ │  [Details]               │ │  │   return ALLOW              ││
│  │ └──────────────────────────┘ │  │ ```                         ││
│  │                              │  │                             ││
│  │ ┌──────────────────────────┐ │  │ [Save Policy]               ││
│  │ │✓ exec("git status")      │ │  │                             ││
│  │ │  Approved by human       │ │  │ Proposals (2 pending)       ││
│  │ │  14:24:33                │ │  │ • Allow git operations      ││
│  │ └──────────────────────────┘ │  │ • Restrict network access   ││
│  │                              │  │ [View All]                  ││
│  │ ┌──────────────────────────┐ │  │                             ││
│  │ │⏸️ exec("npm install")     │ │  │                             ││
│  │ │  PENDING APPROVAL        │ │  │                             ││
│  │ │  [Approve] [Reject]      │ │  │                             ││
│  │ └──────────────────────────┘ │  │                             ││
│  │                              │  │                             ││
│  │ ┌──────────────────────────┐ │  │                             ││
│  │ │✗ curl("evil.com")        │ │  │                             ││
│  │ │  Rejected by policy      │ │  │                             ││
│  │ │  Reason: Blocked domain  │ │  │                             ││
│  │ │  14:25:01                │ │  │                             ││
│  │ └──────────────────────────┘ │  │                             ││
│  │                              │  │                             ││
│  └──────────────────────────────┘  └─────────────────────────────┘│
│                                                                    │
│  (no message composer - external agent)                           │
└────────────────────────────────────────────────────────────────────┘
```

### Timeline Data Sources

**Key insight**: Tool call timeline is **independent** of UI server attachment.

#### 1. Policy Gate Timeline (Always Present)
- **Source**: Policy enforcement layer (not UI server)
- **Captures**: ALL tool calls passing through policy gate
- **Includes**: Auto-approved, user-approved, rejected calls
- **API**: `resource://agents/{id}/approvals/history`

#### 2. UI Server Blocks (Optional)
- **Source**: UI MCP server (when attached)
- **Provides**: Agent-generated UI elements (messages, cards, structured data)
- **Orthogonal to**: Local/remote agent loop distinction
- **API**: `resource://ui/{id}/blocks` (if UI server attached)
