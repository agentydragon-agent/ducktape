# WebSocket → MCP Subscriptions Migration Strategy

**Date**: 2025-11-19
**Wave**: D (Backend Feature Complete)

## Executive Summary

Replace all 6 WebSocket channels with MCP resources + subscriptions. The pattern is:

1. **Backend**: Create MCP resource that returns the data (replaces WS snapshot)
2. **Backend**: Call `server.broadcast_resource_updated(uri)` when data changes (replaces WS broadcast)
3. **Frontend**: Subscribe to resource URI, re-read on notification (replaces WS message handler)

**Key Insight**: MCP subscriptions emit **"resource X updated"** notifications only. Frontend must re-read the full resource to get updated data. This is simpler than streaming individual events.

---

## MCP Subscription Model (How It Works)

### Backend Pattern

```python
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

server = NotifyingFastMCP("example")

# Define resource (returns current state snapshot)
@server.resource("resource://example/state")
async def get_state() -> str:
    return json.dumps({"current_state": get_current_data()})

# Emit notification when state changes (elsewhere in code)
async def on_state_changed():
    await server.broadcast_resource_updated("resource://example/state")
```

### Frontend Pattern

```typescript
import { mcpClient } from './features/mcp/clientManager';

// Subscribe to resource
const unsubscribe = await mcpClient.subscribe(
  'resource://example/state',
  async (notification) => {
    // Notification received - re-read the resource
    const result = await mcpClient.readResource('resource://example/state');
    const state = JSON.parse(result.contents[0].text);

    // Update UI with new state
    stateStore.set(state);
  }
);

// Initial read (no notification for first load)
const initial = await mcpClient.readResource('resource://example/state');
stateStore.set(JSON.parse(initial.contents[0].text));
```

**Key Differences from WebSocket**:
- WebSocket: Pushes individual events (`user_text`, `tool_call`, etc.)
- MCP: Pushes "resource updated" notification, client re-reads full state

---

## Migration Plan by Channel

### 1. `/ws/agents` → `resource://agents/list`

**Current WebSocket**:
- Messages: `agents_snapshot`, `agent_created`, `agent_deleted`, `agent_status`
- Data: List of agents with live status, lifecycle, run phase, pending approvals

**MCP Migration**:

#### Backend

```python
# In agents MCP server (adgn/src/adgn/agent/mcp_bridge/servers/agents.py)

@server.resource("resource://agents/list")
async def agents_list() -> str:
    """Global agent list with status."""
    registry = get_registry()
    agents = []

    for agent_id in registry.list_agent_ids():
        runtime = registry.get(agent_id)
        if not runtime:
            continue

        # Build agent status (same data as WS AgentStatusData)
        status = build_agent_status_core(runtime)
        agents.append({
            "id": agent_id,
            "live": status.live,
            "active_run_id": str(status.active_run_id) if status.active_run_id else None,
            "lifecycle": status.lifecycle,
            "run_phase": status.run_phase,
            "policy": status.policy.model_dump(),
            "ui": status.ui.model_dump(),
            "mcp": status.mcp.model_dump(),
            "container": status.container.model_dump(),
            "pending_approvals": status.pending_approvals,
            "last_event_at": status.last_event_at.isoformat() if status.last_event_at else None,
        })

    return json.dumps({"agents": agents})

# Emit notifications on agent events
async def on_agent_created(agent_id: str):
    await server.broadcast_resource_updated("resource://agents/list")

async def on_agent_deleted(agent_id: str):
    await server.broadcast_resource_updated("resource://agents/list")

async def on_agent_status_changed(agent_id: str):
    await server.broadcast_resource_updated("resource://agents/list")
```

#### Frontend

```typescript
// In AgentsSidebar.svelte

import { agentsStore } from './stores';
import { mcpClient } from './features/mcp/clientManager';

async function subscribeToAgents() {
  // Subscribe to agent list changes
  const unsubscribe = await mcpClient.subscribe(
    'resource://agents/list',
    async () => {
      // Re-read agent list
      const result = await mcpClient.readResource('resource://agents/list');
      const data = JSON.parse(result.contents[0].text);

      // Update store
      agentsStore.set(data.agents);
    }
  );

  // Initial load
  const initial = await mcpClient.readResource('resource://agents/list');
  agentsStore.set(JSON.parse(initial.contents[0].text).agents);

  return unsubscribe;
}
```

**Wire Notifications**: Registry events → `broadcast_resource_updated`

```python
# In agent registry (adgn/src/adgn/agent/runtime/registry.py)

class AgentRegistry:
    async def create_agent(self, ...):
        # ... create agent ...
        await self._mcp_server.broadcast_resource_updated("resource://agents/list")

    async def delete_agent(self, agent_id: str):
        # ... delete agent ...
        await self._mcp_server.broadcast_resource_updated("resource://agents/list")

    async def _on_agent_status_changed(self, agent_id: str):
        await self._mcp_server.broadcast_resource_updated("resource://agents/list")
```

---

### 2. `/ws/session` → `resource://agents/{id}/session/state`

**Current WebSocket**:
- Messages: `session_snapshot`, `user_text`, `assistant_text`, `tool_call`, `tool_result`, `reasoning`, `run_status`, `turn_done`
- Data: Session state, run state, transcript items

**MCP Migration**:

#### Backend

```python
@server.resource("resource://agents/{agent_id}/session/state")
async def agent_session_state(agent_id: str) -> str:
    """Agent session state and transcript."""
    runtime = registry.get(agent_id)
    if not runtime or not runtime.runtime.session:
        raise ValueError(f"Agent {agent_id} has no session")

    session = runtime.runtime.session

    # Build session snapshot (same data as SessionSnapshot)
    data = {
        "session_state": {
            "session_id": session._manager._session_id,
            "version": "1.0.0",
            "capabilities": [],
            "last_event_id": None,  # TODO: track event IDs
            "active_run_id": str(session.active_run.run_id) if session.active_run else None,
            "run_counter": 0,  # TODO: track run counter
        },
        "run_state": {
            "run_id": str(session.active_run.run_id),
            "status": "running",  # TODO: track run status
            "started_at": session.active_run.started_at.isoformat(),
            "finished_at": None,
            "last_event_id": None,
        } if session.active_run else None,
        "transcript": await session.get_transcript_items(),  # New method to fetch transcript
    }

    return json.dumps(data)

# Emit notifications on session events
async def on_session_event(agent_id: str):
    """Called by session on any transcript update."""
    await server.broadcast_resource_updated(f"resource://agents/{agent_id}/session/state")
```

#### Frontend

```typescript
// In ChatPane.svelte

import { sessionStore } from './stores';
import { mcpClient } from './features/mcp/clientManager';

async function subscribeToSession(agentId: string) {
  const uri = `resource://agents/${agentId}/session/state`;

  const unsubscribe = await mcpClient.subscribe(uri, async () => {
    // Re-read session state
    const result = await mcpClient.readResource(uri);
    const data = JSON.parse(result.contents[0].text);

    // Update store with session + transcript
    sessionStore.set(data);
  });

  // Initial load
  const initial = await mcpClient.readResource(uri);
  sessionStore.set(JSON.parse(initial.contents[0].text));

  return unsubscribe;
}
```

**Wire Notifications**: Session events → `broadcast_resource_updated`

```python
# In agent session (adgn/src/adgn/agent/runtime/session.py)

class AgentSession:
    async def on_user_text(self, text: str):
        # ... process user text ...
        await self._notify_session_changed()

    async def on_assistant_text(self, text: str):
        # ... process assistant text ...
        await self._notify_session_changed()

    async def _notify_session_changed(self):
        await self._mcp_server.broadcast_resource_updated(
            f"resource://agents/{self.agent_id}/session/state"
        )
```

---

### 3. `/ws/approvals` → `resource://agents/{id}/approvals/pending`

**Current WebSocket**:
- Messages: `approvals_snapshot`, `approval_pending`, `approval_decision`
- Data: Pending approvals list, approval decisions

**MCP Migration**:

#### Backend

```python
@server.resource("resource://agents/{agent_id}/approvals/pending")
async def agent_approvals_pending(agent_id: str) -> str:
    """Pending approvals for agent."""
    runtime = registry.get(agent_id)
    if not runtime:
        raise ValueError(f"Agent {agent_id} not found")

    approval_hub = runtime.running.approval_hub

    # Build pending approvals list (same data as ApprovalsSnapshot)
    pending = [
        {
            "call_id": req.tool_call.call_id,
            "tool": req.tool_call.tool,
            "args": req.tool_call.args,
        }
        for req in approval_hub._requests.values()
    ]

    return json.dumps({"pending": pending})

# Emit notifications on approval events
async def on_approval_pending(agent_id: str, call_id: str):
    await server.broadcast_resource_updated(
        f"resource://agents/{agent_id}/approvals/pending"
    )

async def on_approval_decided(agent_id: str, call_id: str):
    await server.broadcast_resource_updated(
        f"resource://agents/{agent_id}/approvals/pending"
    )
```

#### Frontend

```typescript
// In ApprovalsPanel.svelte

import { approvalsStore } from './stores';
import { mcpClient } from './features/mcp/clientManager';

async function subscribeToApprovals(agentId: string) {
  const uri = `resource://agents/${agentId}/approvals/pending`;

  const unsubscribe = await mcpClient.subscribe(uri, async () => {
    // Re-read pending approvals
    const result = await mcpClient.readResource(uri);
    const data = JSON.parse(result.contents[0].text);

    // Update store
    approvalsStore.set(data.pending);
  });

  // Initial load
  const initial = await mcpClient.readResource(uri);
  approvalsStore.set(JSON.parse(initial.contents[0].text).pending);

  return unsubscribe;
}
```

**Wire Notifications**: Approval hub events → `broadcast_resource_updated`

```python
# In approval hub (adgn/src/adgn/agent/approvals/hub.py)

class ApprovalHub:
    async def request_approval(self, tool_call: ToolCall):
        # ... add to pending ...
        await self._notify_approvals_changed()

    async def approve(self, call_id: str):
        # ... approve and remove ...
        await self._notify_approvals_changed()

    async def _notify_approvals_changed(self):
        await self._mcp_server.broadcast_resource_updated(
            f"resource://agents/{self.agent_id}/approvals/pending"
        )
```

---

### 4. `/ws/policy` → `resource://agents/{id}/policy/state`

**Current WebSocket**:
- Messages: `policy_snapshot`, `policy_updated`, `policy_proposal`
- Data: Policy content, id, proposals list

**MCP Migration**:

#### Backend

```python
@server.resource("resource://agents/{agent_id}/policy/state")
async def agent_policy_state(agent_id: str) -> str:
    """Policy state and proposals."""
    runtime = registry.get(agent_id)
    if not runtime:
        raise ValueError(f"Agent {agent_id} not found")

    engine = runtime.running.approval_engine

    # Get current policy
    content, policy_id = engine.get_policy()

    # Load proposals from persistence
    db_proposals = await engine.persistence.list_policy_proposals(agent_id)
    proposals = [
        {
            "id": p.id,
            "status": p.status,
            "docstring": None,  # TODO: extract if needed
            "tests": None,  # TODO: parse if available
        }
        for p in db_proposals
    ]

    return json.dumps({
        "policy": {
            "content": content,
            "id": policy_id,
            "proposals": proposals,
        }
    })

# Emit notifications on policy events
async def on_policy_updated(agent_id: str):
    await server.broadcast_resource_updated(
        f"resource://agents/{agent_id}/policy/state"
    )

async def on_proposal_created(agent_id: str, proposal_id: str):
    await server.broadcast_resource_updated(
        f"resource://agents/{agent_id}/policy/state"
    )
```

#### Frontend

```typescript
// In PolicyEditorPane.svelte

import { policyStore } from './stores';
import { mcpClient } from './features/mcp/clientManager';

async function subscribeToPolicy(agentId: string) {
  const uri = `resource://agents/${agentId}/policy/state`;

  const unsubscribe = await mcpClient.subscribe(uri, async () => {
    // Re-read policy state
    const result = await mcpClient.readResource(uri);
    const data = JSON.parse(result.contents[0].text);

    // Update store
    policyStore.set(data.policy);
  });

  // Initial load
  const initial = await mcpClient.readResource(uri);
  policyStore.set(JSON.parse(initial.contents[0].text).policy);

  return unsubscribe;
}
```

**Wire Notifications**: Policy engine events → `broadcast_resource_updated`

```python
# In approval policy engine (adgn/src/adgn/agent/approvals/policy_engine.py)

class ApprovalPolicyEngine:
    async def set_policy(self, content: str):
        # ... update policy ...
        await self._notify_policy_changed()

    async def create_proposal(self, proposal: PolicyProposal):
        # ... create proposal ...
        await self._notify_policy_changed()

    async def _notify_policy_changed(self):
        await self._mcp_server.broadcast_resource_updated(
            f"resource://agents/{self.agent_id}/policy/state"
        )
```

---

### 5. `/ws/mcp` → `resource://agents/{id}/mcp/state`

**Current WebSocket**:
- Messages: `mcp_snapshot`, `mcp_server_attached`, `mcp_server_detached`
- Data: Sampling snapshot (available servers, tools, resources)

**MCP Migration**:

#### Backend

```python
@server.resource("resource://agents/{agent_id}/mcp/state")
async def agent_mcp_state(agent_id: str) -> str:
    """MCP servers state."""
    runtime = registry.get(agent_id)
    if not runtime:
        raise ValueError(f"Agent {agent_id} not found")

    compositor = runtime.running.compositor

    # Get sampling snapshot (same data as McpSnapshot)
    sampling = await compositor.sampling_snapshot()

    return json.dumps({
        "sampling": sampling.model_dump()
    })

# Emit notifications on MCP server events
async def on_mcp_server_attached(agent_id: str, name: str):
    await server.broadcast_resource_updated(
        f"resource://agents/{agent_id}/mcp/state"
    )

async def on_mcp_server_detached(agent_id: str, name: str):
    await server.broadcast_resource_updated(
        f"resource://agents/{agent_id}/mcp/state"
    )
```

#### Frontend

```typescript
// In ServersPanel.svelte

import { mcpServersStore } from './stores';
import { mcpClient } from './features/mcp/clientManager';

async function subscribeToMcpState(agentId: string) {
  const uri = `resource://agents/${agentId}/mcp/state`;

  const unsubscribe = await mcpClient.subscribe(uri, async () => {
    // Re-read MCP state
    const result = await mcpClient.readResource(uri);
    const data = JSON.parse(result.contents[0].text);

    // Update store
    mcpServersStore.set(data.sampling);
  });

  // Initial load
  const initial = await mcpClient.readResource(uri);
  mcpServersStore.set(JSON.parse(initial.contents[0].text).sampling);

  return unsubscribe;
}
```

**Wire Notifications**: Compositor events → `broadcast_resource_updated`

```python
# In compositor (adgn/src/adgn/mcp/compositor/server.py)

class Compositor:
    async def mount_server(self, name: str, spec: ServerSpec):
        # ... mount server ...
        await self._notify_mcp_changed()

    async def unmount_server(self, name: str):
        # ... unmount server ...
        await self._notify_mcp_changed()

    async def _notify_mcp_changed(self):
        await self._mcp_server.broadcast_resource_updated(
            f"resource://agents/{self.agent_id}/mcp/state"
        )
```

---

### 6. `/ws/ui` → `resource://agents/{id}/ui/state`

**Current WebSocket**:
- Messages: `ui_state_snapshot`, `ui_state_updated`, `ui_message`, `ui_end_turn`
- Data: UI state (display items, messages)

**MCP Migration**:

#### Backend

```python
@server.resource("resource://agents/{agent_id}/ui/state")
async def agent_ui_state(agent_id: str) -> str:
    """UI state (optional, only if UI server attached)."""
    runtime = registry.get(agent_id)
    if not runtime or not runtime.runtime.session:
        raise ValueError(f"Agent {agent_id} has no session")

    ui_state = runtime.runtime.session.ui_state

    return json.dumps({
        "seq": ui_state.seq,
        "state": ui_state.model_dump(),
    })

# Emit notifications on UI state changes
async def on_ui_state_changed(agent_id: str):
    await server.broadcast_resource_updated(
        f"resource://agents/{agent_id}/ui/state"
    )
```

#### Frontend

```typescript
// In ChatPane.svelte (UI state handling)

import { uiStateStore } from './stores';
import { mcpClient } from './features/mcp/clientManager';

async function subscribeToUiState(agentId: string) {
  const uri = `resource://agents/${agentId}/ui/state`;

  const unsubscribe = await mcpClient.subscribe(uri, async () => {
    // Re-read UI state
    const result = await mcpClient.readResource(uri);
    const data = JSON.parse(result.contents[0].text);

    // Update store
    uiStateStore.set(data.state);
  });

  // Initial load (graceful degradation if UI not attached)
  try {
    const initial = await mcpClient.readResource(uri);
    uiStateStore.set(JSON.parse(initial.contents[0].text).state);
  } catch (err) {
    // UI server not attached - that's okay
    console.debug('UI server not available for agent', agentId);
  }

  return unsubscribe;
}
```

**Wire Notifications**: UI state events → `broadcast_resource_updated`

```python
# In UI manager (adgn/src/adgn/agent/runtime/ui_manager.py or similar)

class UiManager:
    async def add_display_item(self, item: UiDisplayItem):
        # ... add to UI state ...
        await self._notify_ui_changed()

    async def _notify_ui_changed(self):
        await self._mcp_server.broadcast_resource_updated(
            f"resource://agents/{self.agent_id}/ui/state"
        )
```

---

## Implementation Checklist

### Phase 1: Backend Resources (1 week)

- [ ] Add `resource://agents/list` to agents MCP server
- [ ] Add `resource://agents/{id}/session/state`
- [ ] Add `resource://agents/{id}/approvals/pending`
- [ ] Add `resource://agents/{id}/policy/state`
- [ ] Add `resource://agents/{id}/mcp/state`
- [ ] Add `resource://agents/{id}/ui/state`
- [ ] Wire notification calls in registry (agent create/delete/status)
- [ ] Wire notification calls in session (transcript events)
- [ ] Wire notification calls in approval hub (approval requests/decisions)
- [ ] Wire notification calls in policy engine (policy updates)
- [ ] Wire notification calls in compositor (server attach/detach)
- [ ] Wire notification calls in UI manager (UI state changes)
- [ ] Test all resources return correct data
- [ ] Test all notifications emit on events

### Phase 2: Frontend Migration (1 week)

- [ ] Migrate AgentsSidebar to MCP subscription (`resource://agents/list`)
- [ ] Migrate ChatPane to MCP subscription (`resource://agents/{id}/session/state`)
- [ ] Migrate ApprovalsPanel to MCP subscription (`resource://agents/{id}/approvals/pending`)
- [ ] Migrate PolicyEditorPane to MCP subscription (`resource://agents/{id}/policy/state`)
- [ ] Migrate ServersPanel to MCP subscription (`resource://agents/{id}/mcp/state`)
- [ ] Migrate UI state handling to MCP subscription (`resource://agents/{id}/ui/state`)
- [ ] Test all components receive live updates
- [ ] Test initial load works (no notification needed)
- [ ] Test error handling (resource not found, subscription failed)

### Phase 3: Cleanup (2-3 days)

- [ ] Delete `/ws/agents` endpoint and AgentsWSHub class
- [ ] Delete `/ws/session` endpoint and SessionChannelManager
- [ ] Delete `/ws/approvals` endpoint and ApprovalsChannelManager
- [ ] Delete `/ws/policy` endpoint and PolicyChannelManager
- [ ] Delete `/ws/mcp` endpoint and McpChannelManager
- [ ] Delete `/ws/ui` endpoint and UiChannelManager
- [ ] Delete `adgn/src/adgn/agent/server/channels/` directory
- [ ] Delete channel bundle infrastructure (`bundle.py`)
- [ ] Remove channel references from `app.py`
- [ ] Update tests to use MCP subscriptions
- [ ] Final integration testing

---

## Testing Strategy

### Unit Tests

```python
# Test resource returns correct data
async def test_agents_list_resource():
    server = get_agents_mcp_server()
    result = await server.read_resource("resource://agents/list")
    data = json.loads(result.contents[0].text)
    assert "agents" in data

# Test notification emits
async def test_agent_created_notification():
    server = get_agents_mcp_server()

    # Set up notification recorder
    recorder = NotificationRecorder()
    server._sessions.add(recorder)

    # Create agent
    await registry.create_agent("test-preset")

    # Verify notification sent
    await recorder.wait_for("resource://agents/list")
```

### Integration Tests

```python
# Test frontend subscription receives updates
async def test_agents_list_subscription(page: Page):
    # Navigate to UI
    await page.goto("http://localhost:8081")

    # Subscribe to agents list
    agents_count = await page.locator('[data-testid="agents-count"]').text_content()
    assert int(agents_count) == 0

    # Create agent via MCP tool
    await create_agent_via_mcp("test-preset")

    # Wait for update
    await page.wait_for_selector('[data-testid="agent-test-preset"]')

    # Verify count updated
    agents_count = await page.locator('[data-testid="agents-count"]').text_content()
    assert int(agents_count) == 1
```

---

## Performance Considerations

### Resource Read Frequency

**Concern**: Every notification triggers a full resource read. Could this cause performance issues?

**Mitigations**:
1. **Debouncing**: Frontend debounces rapid notifications (e.g., 100ms)
2. **Efficient Queries**: Resources query only necessary data (no joins, no N+1)
3. **Caching**: Backend can cache resource responses (short TTL ~1s)
4. **Selective Updates**: Only emit notifications for meaningful changes (not internal state)

### Network Traffic

**Comparison**:
- WebSocket: Pushes individual events (~100-500 bytes each)
- MCP: Pushes notification (~50 bytes) + resource read (~1-5KB)

**Analysis**:
- WebSocket: More efficient for high-frequency updates (10+ events/sec)
- MCP: More efficient for low-frequency updates (1 event/5-10 sec)
- Our use case: Low-frequency (agent status changes, approvals, policy updates)

**Conclusion**: MCP subscription pattern is acceptable for our use case.

---

## Rollback Plan

1. **Keep WebSocket channels for 1 release** after MCP migration (dual-mode)
2. **Feature flag**: Toggle between WS and MCP in frontend
3. **Monitoring**: Track MCP subscription success rates
4. **Quick revert**: If issues detected, flip flag back to WebSocket
5. **Graceful degradation**: If MCP fails, fall back to HTTP polling

---

## Open Questions

### 1. `/api/capabilities` Endpoint

**Current**: Returns global server capabilities (`mode: full_agent | mcp_bridge`)

**Problem**: Capabilities are per-agent, not global

**Options**:
- **Option A**: Keep as HTTP bootstrap, return global mode only
- **Option B**: Migrate to `resource://agents/{id}/capabilities` (per-agent)
- **Option C**: Remove endpoint, detect capabilities from MCP tools available

**Recommendation**: **Option B** - per-agent capabilities make more sense. Use `resource://agents/{id}/info` which already exists and includes agent config.

### 2. Presets Endpoint

**Current**: `GET /api/presets` returns list of available presets

**Migration**: `resource://presets/list`

**Backend**:

```python
@server.resource("resource://presets/list")
async def presets_list() -> str:
    """Available agent presets."""
    presets = get_available_presets()  # reads from disk/config
    return json.dumps({
        "presets": [
            {"name": p.name, "description": p.description}
            for p in presets
        ]
    })
```

**Frontend**:

```typescript
async function loadPresets() {
  const result = await mcpClient.readResource('resource://presets/list');
  return JSON.parse(result.contents[0].text).presets;
}
```

**Note**: No subscription needed (presets don't change at runtime)

### 3. Approval History

**Current**: `GET /api/agents/{id}/approvals/history` returns historical approvals

**Migration**: Already has `resource://agents/{id}/approvals/history` (per audit)

**Frontend Update**: Replace HTTP GET with MCP resource read (no subscription needed - history doesn't update in real-time)

---

## Success Criteria

### Wave D Complete When:

- ✅ All 6 WebSocket channels deleted
- ✅ All channel infrastructure code removed
- ✅ 6 MCP resources implemented and tested
- ✅ All notification wiring verified
- ✅ Frontend uses MCP subscriptions exclusively
- ✅ All integration tests pass
- ✅ No WebSocket code remains (grep confirms)

---

**End of Migration Strategy**
