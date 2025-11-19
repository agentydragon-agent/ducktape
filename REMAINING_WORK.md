# Remaining Work - MCP Management UI Implementation

## Status Summary

Based on code inspection and test analysis:

- **Phase 0**: ✅ 100% Complete (but plan checkboxes not updated)
- **Phase 1**: ⚠️ 95% Complete (1 minor gap: agent state sampling)
- **Phase 2**: ❌ 0% Complete (entire frontend MCP client not started)
- **Phase 3**: ❌ 0% Complete (no type generation tooling)
- **Phase 4**: ⚠️ 40% Complete (basic e2e tests exist, but no MCP-specific tests)
- **Phase 5**: ❌ 0% Complete (WebSockets still active)

## What Actually Remains

### Phase 1: Backend Polish (1 task)

#### 1.1 Implement Agent State Sampling
**File**: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py:240`

**Current**:
```python
raise NotImplementedError("Sampling snapshot not yet implemented")
```

**Required**:
- Get sampling snapshot from local agent runtime
- Return snapshot data (current messages, state, etc.)
- Handle case where agent is not in sampling state

**Acceptance**:
- [ ] `resource://agents/{id}/state` returns actual sampling data for local agents
- [ ] Test with agent in different states (idle, sampling, waiting)
- [ ] Error handling for non-local agents works

---

### Phase 2: Frontend MCP Client (ENTIRE PHASE)

**Current Architecture**: Frontend uses WebSocket channels + HTTP API, NOT MCP protocol

**Required**: Replace WebSocket communication with MCP client

#### 2.1 Install MCP SDK
**File**: `adgn/src/adgn/agent/web/package.json`

**Required**:
```bash
npm install @modelcontextprotocol/sdk
```

**Acceptance**:
- [ ] Package appears in package.json dependencies
- [ ] TypeScript types available from `@modelcontextprotocol/sdk/client`

#### 2.2 Create MCP Client Wrapper
**File**: `adgn/src/adgn/agent/web/src/features/mcp/client.ts` (NEW)

**Required**:
- StreamableHTTP transport to `/mcp/agents` endpoint
- Token authentication via Bearer header
- Connection lifecycle management
- Error handling and reconnection logic

**Acceptance**:
- [ ] `createMCPClient(url, token)` returns connected client
- [ ] Client can read resources
- [ ] Client can call tools
- [ ] Client handles connection errors gracefully

#### 2.3 Token Management
**File**: `adgn/src/adgn/agent/web/src/shared/token.ts` (NEW)

**Required**:
- Extract token from URL query parameter on first load
- Store token in localStorage
- Retrieve token from localStorage on subsequent loads
- Clear token on auth failure

**Acceptance**:
- [ ] URL `?token=abc123` extracts and stores token
- [ ] Subsequent page loads use stored token
- [ ] 401 response clears token and shows auth error

#### 2.4 Resource Subscriptions & Notifications
**File**: `adgn/src/adgn/agent/web/src/features/mcp/subscriptions.ts` (NEW)

**Required**:
- Subscribe to `resource://approvals/pending` (global mailbox)
- Subscribe to `resource://agents/{id}/approvals/history` per agent
- Handle `notifications/resources/updated` messages
- Refresh UI when notifications arrive

**Acceptance**:
- [ ] Client subscribes to resources on connection
- [ ] Notifications trigger resource re-fetches
- [ ] UI auto-updates when approvals arrive
- [ ] UI auto-updates when decisions are made

#### 2.5 Agent List Component (MCP)
**File**: `adgn/src/adgn/agent/web/src/components/AgentsSidebar.svelte` (MODIFY)

**Current**: Uses WebSocket `/ws/agents` channel

**Required**:
- Fetch `resource://agents/list` via MCP
- Display agent capabilities (chat, agent_loop)
- Show mode badges (LOCAL vs BRIDGE)
- Subscribe to updates

**Acceptance**:
- [ ] Agent list loads from MCP resource
- [ ] Capabilities displayed correctly
- [ ] Mode badges shown (LOCAL/BRIDGE)
- [ ] List updates when agents added/removed

#### 2.6 Global Approvals Mailbox Component (MCP)
**File**: `adgn/src/adgn/agent/web/src/components/GlobalApprovalsList.svelte` (NEW)

**Required**:
- Fetch `resource://approvals/pending`
- Parse `ReadResourceResult` with multiple `TextResourceContents` blocks
- Display pending approvals from all agents
- Group by agent_id
- Wire approve/reject buttons to MCP tools

**Acceptance**:
- [ ] Displays all pending approvals across agents
- [ ] Handles multiple content blocks correctly
- [ ] Shows agent_id, tool name, and args
- [ ] Approve button calls `approve_tool_call` tool
- [ ] Reject button calls `reject_tool_call` tool
- [ ] Live updates when new approvals arrive

#### 2.7 Timeline Component (NEW)
**File**: `adgn/src/adgn/agent/web/src/components/ApprovalTimeline.svelte` (NEW)

**Required**:
- Fetch `resource://agents/{id}/approvals/history`
- Display chronological timeline of tool calls
- Show PENDING → EXECUTING → COMPLETED states
- Display decision (auto-approved, user-approved, rejected)
- Show tool output for completed calls
- Auto-update when new decisions made

**Acceptance**:
- [ ] Timeline displays historical tool calls
- [ ] States clearly indicated (PENDING/EXECUTING/COMPLETED)
- [ ] Decision method shown (policy/user)
- [ ] Tool outputs displayed
- [ ] Timeline auto-updates via notifications

#### 2.8 Abort Button (MCP)
**File**: `adgn/src/adgn/agent/web/src/components/ChatComposer.svelte` (MODIFY)

**Current**: Uses WebSocket message

**Required**:
- Call `abort_agent` MCP tool
- Only show for LOCAL agents
- Disable during non-sampling states

**Acceptance**:
- [ ] Abort button calls MCP tool
- [ ] Only visible for local agents
- [ ] Properly enabled/disabled based on state

---

### Phase 3: Shared Models (ENTIRE PHASE)

#### 3.1 Setup Type Generation Tooling
**File**: `adgn/src/adgn/agent/web/package.json` (MODIFY)

**Required**:
```bash
npm install --save-dev pydantic-to-typescript
```

Add script:
```json
{
  "scripts": {
    "generate-types": "pydantic-to-typescript ../../persist/__init__.py --output src/generated/types.ts",
    "prebuild": "npm run generate-types"
  }
}
```

**Acceptance**:
- [ ] Package installed
- [ ] Script runs successfully
- [ ] Generated types.ts file created

#### 3.2 Configure Type Generation
**File**: `adgn/scripts/generate_types.py` (NEW)

**Required**:
- Python script to extract Pydantic models
- Generate TypeScript interfaces
- Include all MCP request/response types
- Run as part of build process

**Models to Export**:
- `AgentInfo`, `AgentListResponse`
- `PendingApproval`, `AgentApprovalsPendingResponse`
- `ApprovalHistoryEntry`, `AgentApprovalsHistoryResponse`
- `ToolCall`, `Decision`, `ToolCallExecution`, `ToolCallRecord`
- All tool input types (`ApproveToolCallArgs`, etc.)

**Acceptance**:
- [ ] Script generates valid TypeScript
- [ ] All backend models exported
- [ ] TypeScript compiles without errors
- [ ] No manual type duplication remains

---

### Phase 4: Testing Gaps

#### 4.1 Backend MCP Server Tests (VERIFY EXISTING)

**Current Status**: Tests exist in `adgn/tests/agent/mcp_bridge/test_agents_server.py`

**Gaps to Fill**:
- [ ] Test `resource://agents/{id}/state` for local agents (currently NotImplementedError)
- [ ] Test resource notifications fire correctly
- [ ] Test multi-agent scenarios (2+ agents, mix of local/bridge)
- [ ] Test global mailbox with multiple agents having pending approvals
- [ ] Test historical timeline with mixed decision types (policy/user)

**New Tests Needed**:
```python
# test_agents_server.py additions
async def test_agent_state_local_agent():
    """Test sampling state resource for local agent."""

async def test_resource_notifications_on_approval():
    """Test that notifications fire when approvals change."""

async def test_multi_agent_global_mailbox():
    """Test global mailbox with 2+ agents."""
```

#### 4.2 Frontend MCP Client Tests (NEW)

**File**: `adgn/src/adgn/agent/web/src/features/mcp/client.test.ts` (NEW)

**Required**:
- Test MCP client connection
- Test resource fetching
- Test tool calling
- Test subscription handling
- Test notification processing

**Acceptance**:
- [ ] Client connection test passes
- [ ] Resource read test passes
- [ ] Tool call test passes
- [ ] Subscription test passes
- [ ] Notification handling test passes

#### 4.3 Frontend Component Tests (NEW)

**Files**:
- `AgentsSidebar.test.ts`
- `GlobalApprovalsList.test.ts`
- `ApprovalTimeline.test.ts`

**Required**:
- Test component rendering with mock data
- Test user interactions (clicks, approvals)
- Test state updates on notifications
- Use @testing-library/svelte

**Acceptance**:
- [ ] All component tests pass
- [ ] Test coverage ≥80% for new components

#### 4.4 Playwright E2E Tests (NEW SCENARIOS)

**Current Status**: Tests exist but only cover WebSocket-based flows

**New Tests Required**:

**File**: `adgn/tests/agent/e2e/test_mcp_ui.py` (NEW)

```python
@pytest.mark.e2e
async def test_mcp_approval_flow_with_notifications():
    """Test MCP client receives approval notifications in real-time."""
    # Create agent, attach MCP server
    # Open UI (uses MCP client)
    # Send prompt that triggers tool call
    # Verify approval appears WITHOUT page reload
    # Click approve
    # Verify timeline updates WITHOUT page reload

@pytest.mark.e2e
async def test_multi_agent_global_mailbox():
    """Test global mailbox shows approvals from multiple agents."""
    # Create 2 agents
    # Trigger tool calls in both
    # Open UI
    # Verify global mailbox shows both approvals
    # Approve one
    # Verify mailbox updates to show only remaining approval

@pytest.mark.e2e
async def test_timeline_displays_historical_decisions():
    """Test timeline component shows approval history."""
    # Create agent
    # Make several tool calls with different outcomes
    # Open UI
    # Navigate to timeline view
    # Verify all historical calls displayed
    # Verify states (PENDING/COMPLETED/REJECTED) shown correctly
```

**Acceptance**:
- [ ] MCP approval flow test passes
- [ ] Multi-agent mailbox test passes
- [ ] Timeline display test passes
- [ ] Real-time updates verified via Playwright assertions

#### 4.5 Coverage Configuration

**File**: `adgn/pyproject.toml` (MODIFY)

**Required**:
```toml
[tool.coverage.run]
source = ["adgn"]
omit = ["*/tests/*", "*/test_*.py"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

**File**: `.coveragerc` (NEW)

**Acceptance**:
- [ ] Coverage runs with pytest
- [ ] Coverage report shows ≥80% for new code
- [ ] Coverage fails CI if below threshold

---

### Phase 5: Cleanup (ENTIRE PHASE)

#### 5.1 Remove WebSocket Endpoints

**Files to Modify/Delete**:
- `adgn/src/adgn/agent/server/agents_ws.py` (DELETE)
- `adgn/src/adgn/agent/server/channels/` (DELETE entire directory)
- `adgn/src/adgn/agent/server/ws.py` (DELETE)
- `adgn/src/adgn/agent/server/app.py` (MODIFY - remove WS routes)

**WebSocket Endpoints to Remove**:
1. `/ws/agents` (global agent list)
2. `/ws/ui` (UI state channel)
3. `/ws/policy` (policy channel)
4. `/ws/mcp` (MCP server state)
5. `/ws/approvals` (approval requests)
6. `/ws/session` (agent execution state)

**Acceptance**:
- [ ] All `/ws/*` routes removed from app.py
- [ ] WebSocket handler code deleted
- [ ] Frontend doesn't import any WebSocket code
- [ ] All tests still pass (using MCP)

#### 5.2 Remove Dead Code

**Files to Check**:
- Remove unused imports
- Remove commented-out code blocks
- Remove TODO comments that are now done
- Remove backwards-compatibility shims

**Run**:
```bash
ruff check --select F401  # Unused imports
ruff check --select ERA001  # Commented-out code
```

**Acceptance**:
- [ ] No unused imports
- [ ] No commented-out code
- [ ] All TODOs addressed or documented as future work

#### 5.3 Update Documentation

**Files to Update**:
- `README.md` - Update architecture section
- `AGENTS.md` - Update development workflow
- `plan.md` - Mark all checkboxes as complete
- Add `docs/MCP_ARCHITECTURE.md` - Document new MCP-based system

**New Documentation Required**:

**File**: `docs/MCP_ARCHITECTURE.md` (NEW)

**Contents**:
- Overview of MCP-based management UI
- Resource structure (`resource://agents/...`)
- Tool catalog (approve/reject/abort)
- Notification flow
- Multi-agent support
- Token authentication

**Acceptance**:
- [ ] README.md updated
- [ ] AGENTS.md updated
- [ ] plan.md checkboxes marked complete
- [ ] MCP_ARCHITECTURE.md created and reviewed

---

## Summary of Remaining Work

| Phase | Tasks | Estimated Effort |
|-------|-------|-----------------|
| **Phase 1** | 1 task (agent state) | 1 hour |
| **Phase 2** | 8 tasks (entire frontend) | 12-16 hours |
| **Phase 3** | 2 tasks (type generation) | 2-3 hours |
| **Phase 4** | 5 tasks (test gaps) | 6-8 hours |
| **Phase 5** | 3 tasks (cleanup) | 3-4 hours |
| **Total** | 19 tasks | **24-32 hours** |

## Critical Path

```
Phase 1 (1h) → Phase 2 (16h) → Phase 4 (8h) → Phase 5 (4h)
                    ↓
               Phase 3 (3h) ─────────┘
```

**Longest path**: Phase 2 → Phase 4 → Phase 5 = ~28 hours

**Parallelizable**: Phase 3 can run alongside Phase 2/4

---

## What Was Already Completed

✅ **Phase 0 - Complete**:
- Type consolidation (ToolCall)
- Persistence models (Decision, ToolCallExecution, ToolCallRecord)
- Database schema updates
- Middleware bug fixes
- Execution tracking

✅ **Phase 1 - 95% Complete**:
- Unified agents MCP server
- All resources (except agent state)
- All tools
- Token authentication
- CLI integration
- Comprehensive backend tests

❌ **Phases 2-5 - Not Started**
