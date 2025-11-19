# WebSocket Endpoints Analysis Report
**Agent 5.1 - Remove WebSocket Endpoints**
**Date**: 2025-11-19

## Executive Summary

After thorough analysis, I found that **the monolithic WebSocket endpoint has already been removed** in commit `2b23d5d` (2025-11-18). The codebase has successfully migrated to a modular channel-based architecture. However, there are **test fixtures** that still reference the old endpoint and need to be updated.

---

## Current WebSocket Architecture

### ✅ Active Modular Channels (KEEP - In Use)

All of these are actively used by the frontend and backend:

#### 1. `/ws/agents` - Agent Hub
- **File**: `/home/user/ducktape/adgn/src/adgn/agent/server/agents_ws.py`
- **Purpose**: Broadcasts agent lifecycle events (created/deleted/status)
- **Messages**: `AgentsSnapshotMsg`, `AgentCreatedMsg`, `AgentDeletedMsg`, `AgentStatusMsg`
- **Status**: ✅ **KEEP** - Active, used by frontend

#### 2. `/ws/session` - Agent Session Channel
- **File**: `/home/user/ducktape/adgn/src/adgn/agent/server/channels/session.py`
- **Purpose**: Agent execution state and transcript
- **Messages**: Session snapshots, user/assistant text, tool calls, results, reasoning
- **Status**: ✅ **KEEP** - Active, used for chat transcript

#### 3. `/ws/mcp` - MCP Channel
- **File**: `/home/user/ducktape/adgn/src/adgn/agent/server/channels/mcp.py`
- **Purpose**: MCP server state and sampling snapshots
- **Messages**: `McpSnapshot`, `McpServerAttached`, `McpServerDetached`
- **Status**: ✅ **KEEP** - Active, required for MCP integration

#### 4. `/ws/approvals` - Approvals Channel
- **File**: `/home/user/ducktape/adgn/src/adgn/agent/server/channels/approvals.py`
- **Purpose**: Tool approval requests and decisions
- **Messages**: `ApprovalsSnapshot`, `ApprovalPendingEvt`, `ApprovalDecisionEvt`
- **Status**: ✅ **KEEP** - Active, required for approval workflow

#### 5. `/ws/policy` - Policy Channel
- **File**: `/home/user/ducktape/adgn/src/adgn/agent/server/channels/policy.py`
- **Purpose**: Approval policy state and proposals
- **Messages**: `PolicySnapshot`, `PolicyUpdated`, `PolicyProposalEvt`
- **Status**: ✅ **KEEP** - Active, required for policy management

#### 6. `/ws/ui` - UI Channel
- **File**: `/home/user/ducktape/adgn/src/adgn/agent/server/channels/ui.py`
- **Purpose**: UI state snapshots and custom messages
- **Messages**: `UiStateSnapshot`, `UiStateUpdated`, `UiMessageEvt`, `UiEndTurnEvt`
- **Status**: ✅ **KEEP** - Active, optional but in use

---

## ❌ Obsolete Code - Already Deleted

These were removed in commit `2b23d5d`:

### Backend
- ❌ `/ws` endpoint - **DELETED** (was in `src/adgn/agent/server/ws.py`, 236 lines removed)
- ❌ `ws.py` module - **DELETED**

### Frontend
- ❌ Monolithic WebSocket client - **DELETED** (was in `web/src/features/chat/ws.ts`, 53 lines removed)
- ✅ Frontend migrated to `channels.ts` and `stores_channels.ts`

---

## ⚠️ Issues Found - Need Fixing

### 1. Test Fixture Using Old Endpoint

**File**: `/home/user/ducktape/adgn/tests/agent/conftest.py` (line 347)

```python
# BROKEN - Uses removed /ws endpoint
with client.websocket_connect(f"/ws?agent_id={agent_id}") as ws:
```

This fixture (`ws_session` and `agent_ws_box`) is used by **9 tests**:
1. `test_agents_list_status_and_history`
2. `test_agents_ws_run_status_mirrors`
3. `test_approval_prompt_auto_appears`
4. `test_persist_revive_continue_ui_flow`
5. `test_set_policy_rejects_when_tests_missing`
6. `test_set_policy_rejects_when_test_fails`
7. `test_ui_websocket_roundtrip_with_mocked_openai`
8. `test_ws_plain_assistant_text`
9. `test_ws_tool_multiturn`

### 2. Test Using Old Endpoint Directly

**File**: `/home/user/ducktape/adgn/tests/agent/server/test_agents_ws.py` (line 59)

```python
# BROKEN - Uses removed /ws endpoint
with client.websocket_connect(f"/ws?agent_id={agent_id}") as agent_ws:
```

Test: `test_agents_ws_status_on_agent_ws_connect`

---

## ✅ Infrastructure Files - Keep

These support the modular channel architecture:

- `/home/user/ducktape/adgn/src/adgn/agent/server/channels/__init__.py`
- `/home/user/ducktape/adgn/src/adgn/agent/server/channels/base.py` - `ChannelConnectionManager` base class
- `/home/user/ducktape/adgn/src/adgn/agent/server/channels/common.py` - Shared utilities
- `/home/user/ducktape/adgn/src/adgn/agent/server/channels/endpoints.py` - Registration
- `/home/user/ducktape/adgn/src/adgn/agent/server/channels/bundle.py` - Channel bundle
- `/home/user/ducktape/adgn/src/adgn/agent/server/protocol.py` - Message types
- `/home/user/ducktape/adgn/src/adgn/agent/server/runtime.py` - `ConnectionManager`

---

## Frontend WebSocket Usage

### Active Files (Keep)
- ✅ `/home/user/ducktape/adgn/src/adgn/agent/web/src/features/chat/channels.ts` - Modular channel manager
- ✅ `/home/user/ducktape/adgn/src/adgn/agent/web/src/features/chat/stores_channels.ts` - Channel stores
- ✅ `/home/user/ducktape/adgn/src/adgn/agent/web/src/features/agents/stores.ts` - Agent hub WS

### Components Using Channels
- ✅ `ApprovalTimeline.svelte` - Uses `/ws/agents/${agentId}/approvals` pattern
- ✅ All major components migrated to modular channels

---

## Recommended Actions

### Phase 1: Fix Test Fixtures (High Priority)

#### Option A: Update to Use Session Channel
Replace the old `/ws` endpoint with `/ws/session`:

```python
# In conftest.py, line 347
with client.websocket_connect(f"/ws/session?agent_id={agent_id}") as ws:
```

#### Option B: Use Multiple Channels
If tests need full state, connect to multiple channels:

```python
# Example pattern
with client.websocket_connect(f"/ws/mcp?agent_id={agent_id}") as ws_mcp:
    with client.websocket_connect(f"/ws/session?agent_id={agent_id}") as ws_session:
        # ... test logic
```

### Phase 2: Update Test Expectations

Tests will need to adapt to the new envelope format:

**Old format** (removed):
```json
{
  "session_id": "...",
  "event_id": 123,
  "event_at": "...",
  "payload": { "type": "...", ... }
}
```

**New format** (channel-specific):
```json
{
  "channel": "session",
  "event_id": 123,
  "event_at": "...",
  "payload": { "type": "...", ... }
}
```

### Phase 3: Verify All Tests Pass

After updates, run:
```bash
pytest tests/agent/server/ -v
```

---

## Summary

### ✅ What's Already Done
- ✅ Monolithic `/ws` endpoint removed
- ✅ Modular channels implemented and working
- ✅ Frontend fully migrated
- ✅ Most tests updated

### ⚠️ What Needs Fixing
- ⚠️ Update `ws_session` fixture in `conftest.py` (1 file, ~9 tests affected)
- ⚠️ Update `test_agents_ws_status_on_agent_ws_connect` (1 test)
- ⚠️ Verify all affected tests pass

### 📊 Impact Assessment
- **Files to delete**: 0 (already deleted)
- **Files to modify**: 2 (conftest.py, test_agents_ws.py)
- **Tests affected**: ~10
- **Risk level**: LOW (changes are test-only, no production code)

---

## Acceptance Criteria Met

✅ Analysis report created
✅ Safe deletions identified: **None needed** (already done)
✅ Broken imports identified: **Test fixtures need updates**
✅ Migration path documented

**Conclusion**: The WebSocket migration to MCP channels is **complete** in production code. Only test fixtures need updating to use the new modular channels.
