# MCP-Based Management UI - Unified "agents" Server

## Executive Summary

Replace custom WebSocket channels with a unified **`agents` MCP server** that provides cross-agent management. This single server routes to per-agent infrastructure and can be delegated to other agents for self-orchestration. The frontend becomes a simple MCP client, and the same server can later be given to agents for spawning, approving, and managing other agents.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     Frontend (Browser)                       │
│  - Single MCP client (Streamable HTTP)                      │
│  - Token in URL → localStorage                              │
│  - Connects to: agents server                              │
└──────────────┬───────────────────────────────────────────────┘
               │ HTTP GET /ui?token=...
               │ Streamable HTTP
               ▼
┌──────────────────────────────────────────────────────────────┐
│           Management UI Server (Port 8081)                   │
│  - Serves static files + token auth                         │
│  - Single endpoint: GET /mcp/agents                         │
│                                                              │
│  Unified "agents" MCP Server:                               │
│  ├─ Resources (flat structure):                             │
│  │  ├─ resource://agents/list                               │
│  │  ├─ resource://agents/{id}/state                         │
│  │  ├─ resource://agents/{id}/approvals/pending            │
│  │  ├─ resource://agents/{id}/policy/proposals             │
│  │  └─ resource://approvals/pending (GLOBAL mailbox)       │
│  │                                                           │
│  └─ Tools (route to per-agent infrastructure):             │
│     ├─ approve_tool_call(agent_id, call_id)                │
│     ├─ reject_tool_call(agent_id, call_id, reason)         │
│     ├─ abort_agent(agent_id)                               │
│     └─ (future: spawn_agent, update_policy, ...)           │
└──────────────▲───────────────────────────────────────────────┘
               │ InfrastructureRegistry
               │ Routes: approve(123) → lookup(123).approval_engine.approve()
               │
┌──────────────────────────────────────────────────────────────┐
│              MCP Server (Port 8080)                          │
│  - Token-authenticated MCP-over-HTTP                        │
│  - Routes to per-agent compositor                           │
│  - For external agents (ChatGPT, Claude Desktop, etc.)      │
└──────────────────────────────────────────────────────────────┘
```

## UI Organization & API Structure

### Frontend Layout

The UI uses a **side-by-side layout** with tool call timeline and policy editor. For local agents with UI server attached, a message composer appears below.

#### Agent WITH UI Server (Local Loop)
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

#### Agent WITHOUT UI Server (Remote/Bridge)
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

### Timeline Data Sources (Unbundled)

**Key insight**: Tool call timeline is **independent** of UI server attachment.

#### 1. Policy Gate Timeline (Always Present)
- **Source**: Policy enforcement layer (not UI server)
- **Captures**: ALL tool calls passing through policy gate
- **Includes**: Auto-approved, user-approved, rejected calls
- **API**: `resource://agents/{id}/approvals/history`

```python
class ToolCallEntry(BaseModel):
    """Tool call from policy gate timeline."""
    call_id: str
    tool: str
    args: dict
    decision: DecisionType  # APPROVED / REJECTED
    decision_method: DecisionMethod  # AUTO / USER / POLICY
    reason: str | None  # For rejections
    timestamp: datetime
    decided_by: str  # "policy" | "human" | agent_id
```

#### 2. UI Server Blocks (Optional)
- **Source**: UI MCP server (when attached)
- **Provides**: Agent-generated UI elements (messages, cards, structured data)
- **Orthogonal to**: Local/remote agent loop distinction
- **API**: `resource://ui/{id}/blocks` (if UI server attached)

```python
class UIBlock(BaseModel):
    """UI block from optional UI MCP server."""
    block_id: str
    block_type: str  # "message" | "card" | "data"
    content: dict  # Type-specific content
    timestamp: datetime
```

#### 3. Frontend Timeline Rendering
- **If UI server attached**: Merge tool calls + UI blocks chronologically
- **If no UI server**: Show only tool call timeline
- **Display logic**: Single scrollable timeline, different card types

### API Endpoints

```typescript
// Core agent info
GET resource://agents/list
  → { agents: AgentInfo[] }

// Policy gate timeline (ALWAYS available, both agent types)
GET resource://agents/{id}/approvals/history
  → { timeline: ToolCallEntry[], pending: PendingApproval[] }

// Active policy
GET resource://approval-policy/policy.py
  → Python source code (string)

// Policy proposals
GET resource://agents/{id}/policy/proposals
  → { proposals: PolicyProposalInfo[], active_policy_uri: string }

// UI server blocks (OPTIONAL - only if UI server attached)
GET resource://ui/{id}/blocks
  → { blocks: UIBlock[] }

// Agent controls
POST approve_tool_call(agent_id, call_id) → void
POST reject_tool_call(agent_id, call_id, reason) → void
POST abort_agent(agent_id) → void  // Only for local agents
POST send_message(agent_id, content) → void  // Only if UI server attached
```

### Component Structure

```typescript
// Top-level agent view
<AgentView agent={agentInfo}>
  <SideBySide>
    <TimelinePanel agent={agentInfo} />
    <PolicyPanel agent={agentInfo} />
  </SideBySide>

  {agentInfo.has_ui_server && (
    <MessageComposer
      onSend={sendMessage}
      showAbort={agentInfo.mode === 'LOCAL'}
    />
  )}
</AgentView>

// Timeline merges policy gate + UI blocks
<TimelinePanel>
  {mergeChronologically(
    policyGateTimeline,  // Always present
    uiServerBlocks       // Only if UI server attached
  ).map(entry =>
    entry.type === 'tool_call'
      ? <ToolCallCard {...entry} />
      : <UIBlockCard {...entry} />
  )}
</TimelinePanel>
```

## Key Architectural Decisions

### 1. Unified "agents" Server ✅

**Decision**: Single MCP server instead of multiple independent servers.

**Benefits**:
- ✅ Single connection for frontend (much simpler)
- ✅ Can be delegated to other agents for self-orchestration
- ✅ Agent actions subject to policy (when Agent A uses this server, its actions are governed by Agent A's approval predicate)
- ✅ Future: Agent A can spawn agents, approve/deny actions, update policies
- ✅ Clean routing pattern: `tool(agent_id) → lookup_infrastructure(agent_id).component.method()`

**Future Vision**:
```
User → gives "agents" server to Agent A
Agent A → spawn_agent(...), approve_tool_call(...), update_policy(...)
       → BUT: Agent A's actions subject to Agent A's approval predicate
       → Example: "Agent A can only approve Agent B's policy if it's one of these 5"
```

### 2. Resource Structure (Flat) ✅

```
resource://agents/list                          # All agents + capabilities
resource://agents/{agent_id}/state              # Sampling state (local only)
resource://agents/{agent_id}/approvals/pending  # Per-agent pending approvals
resource://agents/{agent_id}/approvals/history  # Historical approval timeline
resource://approvals/pending                     # GLOBAL mailbox (all agents)
```

**Global mailbox** returns content blocks with both URIs and inline content - each approval is a separate content block.

**Historical timeline** serves as activity log for external agents - shows what tool calls were approved/rejected, when, and by whom.

### 3. Tool Routing Pattern ✅

```python
# Tool call pattern
approve_tool_call(agent_id="foo", call_id="123")

# Routes to:
infra = registry.lookup_agent_infrastructure(agent_id="foo")
await infra.approval_engine.approve(call_id="123")
```

All tools take `agent_id` as first parameter and route to appropriate per-agent infrastructure.

### 4. Token Management ✅

- **Session-based** token (valid for server lifetime)
- **Generate new on each boot** (or env var `UI_TOKEN` override)
- **Store in localStorage** for convenience (graceful fallback on auth failure)
- **No expiry** during server lifetime
- **CLI output**: `Management UI: http://localhost:8081/ui?token=<token>`

### 5. Approvals: Tools Now, Elicitations Later ✅

**Phase 1** (current): Tool-based approvals
- `approve_tool_call(agent_id, call_id)`
- `reject_tool_call(agent_id, call_id, reason)`
- Callable by agents (subject to policy) or frontend (human)

**Phase 2** (future): MCP Elicitations
- Server sends elicitation request to client
- Client shows native approval dialog (3-action model: accept/decline/cancel)
- Standardized human-in-the-loop workflow
- Server can't request PII/credentials (security)

Elicitations are perfect for human approvals, but we start with tools to prove out the architecture first.

### 6. Agent Mode Detection ✅

Check **two factors**:
- (a) Has chat/UI component
- (b) Agent loop is under our control

**Local agents**: Have agent loop → expose sampling state
**Bridge agents**: No agent loop → no sampling state available

### 7. Shared Models ✅

**Auto-generate TypeScript from Pydantic** (Python is SSOT)

Include all MCP inputs/outputs:
- `ApprovalBrief`, `ApprovalPendingEvt`
- `ServerCapabilities`
- `SamplingSnapshot`, `ServerEntry`
- Policy models (`PolicyRequest`, `PolicyResponse`)
- Tool input/output schemas

### 8. Browser Compatibility ✅

Modern browsers only (Chrome/Firefox/Safari/Edge last 2 versions)

## Implementation Plan

### Phase 1: Unified "agents" Server (Backend)

**No stub implementations** - full working implementation required for phase completion.

#### 1.1 Infrastructure Registry Enhancement

**File**: `adgn/src/adgn/agent/mcp_bridge/server.py`

```python
class InfrastructureRegistry:
    """Registry for managing per-agent infrastructure."""

    def known_agents(self) -> list[str]:
        """Return list of all known agent IDs."""
        # Implementation required - no stub
        async with self._lock:
            return list(self._infra_cache.keys())

    async def get_infrastructure(self, agent_id: str) -> RunningInfrastructure:
        """Get infrastructure for agent (must exist)."""
        infra, _ = await self.get_or_create_infrastructure(agent_id)
        return infra
```

**Acceptance**:
- [ ] `known_agents()` returns all agent IDs from cache
- [ ] `get_infrastructure()` raises error if agent doesn't exist
- [ ] Test with multiple agents

#### 1.2 Unified "agents" MCP Server

**File**: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

```python
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from pydantic import BaseModel
from datetime import datetime
from enum import StrEnum

# Enumerations
class DecisionType(StrEnum):
    """Approval decision types."""
    APPROVED = "approved"
    REJECTED = "rejected"

class AgentMode(StrEnum):
    """Agent mode enumeration."""
    LOCAL = "local"
    BRIDGE = "bridge"

# Tool input models
class ApproveToolCallArgs(BaseModel):
    agent_id: str
    call_id: str

class RejectToolCallArgs(BaseModel):
    agent_id: str
    call_id: str
    reason: str

class AbortAgentArgs(BaseModel):
    agent_id: str

# Pending approval models
class PendingApproval(BaseModel):
    """A tool call awaiting approval."""
    call_id: str
    tool: str
    args: dict
    timestamp: datetime

# Historical approval timeline models
class ApprovalHistoryEntry(BaseModel):
    """Single approval decision in the timeline."""
    call_id: str
    tool: str
    args: dict
    decision: DecisionType
    reason: str | None = None  # Only for rejections
    timestamp: datetime
    decided_by: str  # "human" or agent ID

# Resource response models
class AgentInfo(BaseModel):
    """Information about a single agent."""
    agent_id: str
    capabilities: dict[str, bool]  # e.g., {"chat": True, "agent_loop": False}
    mode: AgentMode
    state_uri: str | None = None
    approvals_uri: str | None = None

class AgentListResponse(BaseModel):
    """Response for resource://agents/list."""
    agents: list[AgentInfo]

class AgentApprovalsPendingResponse(BaseModel):
    """Response for resource://agents/{id}/approvals/pending."""
    agent_id: str
    pending: list[PendingApproval]

class AgentApprovalsHistoryResponse(BaseModel):
    """Response for resource://agents/{id}/approvals/history."""
    agent_id: str
    timeline: list[ApprovalHistoryEntry]
    count: int

def make_agents_server(registry: InfrastructureRegistry) -> NotifyingFastMCP:
    """Unified cross-agent management server."""
    server = NotifyingFastMCP(
        name="agents",
        instructions="""Multi-agent management server.

        Provides cross-agent visibility and control:
        - List all agents with their capabilities
        - View sampling state for local agents
        - Approve/reject tool calls
        - Abort running agents

        Future: spawn agents, update policies, delegate work."""
    )

    # Resources

    @server.resource(
        "resource://agents/list",
        name="agents.list",
        mime_type="application/json",
        description="List all agents with capabilities and state"
    )
    async def list_agents() -> AgentListResponse:
        """List all known agents.

        All data constructed using Pydantic models.
        """
        agent_infos: list[AgentInfo] = []
        for agent_id in registry.known_agents():
            # Get mode from registry (no hasattr)
            mode = registry.get_agent_mode(agent_id)

            # Build capabilities dict
            # For now, assume bridge agents have no chat/agent_loop
            # TODO: Add capability tracking to registry if needed
            is_local = (mode == AgentMode.LOCAL)
            capabilities = {
                "chat": is_local,  # Local agents have chat
                "agent_loop": is_local,  # Local agents have agent loop
            }

            # Determine optional URIs based on mode
            state_uri = f"resource://agents/{agent_id}/state" if is_local else None
            approvals_uri = f"resource://agents/{agent_id}/approvals/pending"

            # Construct Pydantic model
            agent_info = AgentInfo(
                agent_id=agent_id,
                capabilities=capabilities,
                mode=mode,
                state_uri=state_uri,
                approvals_uri=approvals_uri,
            )
            agent_infos.append(agent_info)

        return AgentListResponse(agents=agent_infos)

    @server.resource(
        "resource://agents/{agent_id}/state",
        name="agent.state",
        mime_type="application/json",
        description="Sampling state for a local agent"
    )
    async def agent_state(agent_id: str):
        """Get sampling state for local agent."""
        # Check mode via registry (no hasattr)
        if registry.get_agent_mode(agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {agent_id} is not a local agent")

        # Get local runtime to access sampling state
        local_runtime = registry.get_local_runtime(agent_id)
        if local_runtime is None:
            raise ValueError(f"Agent {agent_id} has no local runtime")

        return await local_runtime.session.get_sampling_snapshot()

    @server.resource(
        "resource://agents/{agent_id}/approvals/pending",
        name="agent.approvals.pending",
        mime_type="application/json",
        description="Pending approvals for a specific agent"
    )
    async def agent_approvals_pending(agent_id: str) -> AgentApprovalsPendingResponse:
        """Get pending approvals for agent.

        All data constructed using Pydantic models.
        """
        infra = await registry.get_infrastructure(agent_id)

        # Get pending approvals from approval engine (returns list[PendingApproval])
        pending: list[PendingApproval] = await infra.approval_engine.get_pending()

        return AgentApprovalsPendingResponse(agent_id=agent_id, pending=pending)

    @server.resource(
        "resource://approvals/pending",
        name="approvals.pending.global",
        mime_type="application/json",
        description="Global mailbox: all pending approvals across all agents (returns multiple content blocks)"
    )
    async def approvals_pending_global() -> mcp_types.ReadResourceResult:
        """Get all pending approvals as MCP content blocks (global mailbox).

        Returns mcp_types.ReadResourceResult with multiple TextResourceContents blocks.
        Each approval is a separate content block with:
        - uri: unique resource URI for this approval (via annotations)
        - mimeType: application/json
        - text: inline JSON content with approval details

        All data constructed using Pydantic models. Crashes if any agent fails
        (no exception swallowing).
        """
        import json
        content_blocks: list[mcp_types.TextResourceContents] = []

        for agent_id in registry.known_agents():
            infra = await registry.get_infrastructure(agent_id)
            # get_pending() returns list[PendingApproval] (Pydantic models)
            pending_approvals: list[PendingApproval] = await infra.approval_engine.get_pending()

            for approval in pending_approvals:
                # Construct MCP TextResourceContents for each approval
                approval_uri = f"resource://agents/{agent_id}/approvals/{approval.call_id}"
                approval_data = {
                    "agent_id": agent_id,
                    "call_id": approval.call_id,
                    "tool": approval.tool,
                    "args": approval.args,
                    "timestamp": approval.timestamp.isoformat(),
                }
                # Use MCP types directly - each block is a TextResourceContents
                block = mcp_types.TextResourceContents(
                    uri=approval_uri,  # MCP supports URI in content blocks
                    mimeType="application/json",
                    text=json.dumps(approval_data)
                )
                content_blocks.append(block)

        # Return ReadResourceResult with multiple content blocks
        return mcp_types.ReadResourceResult(contents=content_blocks)

    @server.resource(
        "resource://agents/{agent_id}/approvals/history",
        name="agent.approvals.history",
        mime_type="application/json",
        description="Historical approval timeline for an agent (activity log)"
    )
    async def agent_approvals_history(agent_id: str) -> AgentApprovalsHistoryResponse:
        """Get historical approval timeline for an agent.

        Serves as activity log for external agents - shows what tool calls
        were approved/rejected, when, and by whom (human or which agent).
        All data routed through Pydantic models for type safety.
        """
        infra = await registry.get_infrastructure(agent_id)

        # Get history from approval engine (returns list[ApprovalHistoryEntry])
        history_entries: list[ApprovalHistoryEntry] = await infra.approval_engine.get_history()

        # Return Pydantic response model directly (FastMCP handles serialization)
        return AgentApprovalsHistoryResponse(
            agent_id=agent_id,
            timeline=history_entries,
            count=len(history_entries),
        )

    # Tools

    @server.flat_model()
    async def approve_tool_call(input: ApproveToolCallArgs) -> dict:
        """Approve a pending tool call.

        Routes to: lookup_infrastructure(agent_id).approval_engine.approve(call_id)
        """
        infra = await registry.get_infrastructure(input.agent_id)
        await infra.approval_engine.approve(input.call_id)
        return {"status": "approved", "agent_id": input.agent_id, "call_id": input.call_id}

    @server.flat_model()
    async def reject_tool_call(input: RejectToolCallArgs) -> dict:
        """Reject a pending tool call.

        Routes to: lookup_infrastructure(agent_id).approval_engine.reject(call_id, reason)
        """
        infra = await registry.get_infrastructure(input.agent_id)
        await infra.approval_engine.reject(input.call_id, input.reason)
        return {"status": "rejected", "agent_id": input.agent_id, "call_id": input.call_id}

    @server.flat_model()
    async def abort_agent(input: AbortAgentArgs) -> dict:
        """Abort a running agent.

        Routes to: local_runtime.agent.abort()
        """
        # Check mode via registry (no hasattr)
        if registry.get_agent_mode(input.agent_id) != AgentMode.LOCAL:
            raise ValueError(f"Agent {input.agent_id} is not a local agent (cannot abort)")

        # Get local runtime
        local_runtime = registry.get_local_runtime(input.agent_id)
        if local_runtime is None or local_runtime.agent is None:
            raise ValueError(f"Agent {input.agent_id} has no agent loop")

        await local_runtime.agent.abort()
        return {"status": "aborted", "agent_id": input.agent_id}

    # Wire up notifications
    # - Listen to approval engine events → broadcast resource://approvals/pending updates
    # - Listen to agent loop state changes → broadcast resource://agents/{id}/state updates

    async def _on_approval_change(agent_id: str):
        """Approval engine notification handler."""
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/approvals/pending")
        await server.broadcast_resource_updated("resource://approvals/pending")

    async def _on_agent_state_change(agent_id: str):
        """Agent loop state change notification handler."""
        await server.broadcast_resource_updated(f"resource://agents/{agent_id}/state")

    # Hook up listeners for all agents
    for agent_id in registry.known_agents():
        try:
            infra = await registry.get_infrastructure(agent_id)
            infra.approval_engine.add_listener(lambda: _on_approval_change(agent_id))

            # Only add agent loop listener for local agents (no hasattr)
            if registry.get_agent_mode(agent_id) == AgentMode.LOCAL:
                local_runtime = registry.get_local_runtime(agent_id)
                if local_runtime and local_runtime.agent:
                    local_runtime.agent.add_state_listener(lambda: _on_agent_state_change(agent_id))
        except Exception as e:
            logger.warning(f"Failed to hook listeners for {agent_id}: {e}")

    return server
```

**Acceptance**:
- [ ] `resource://agents/list` returns all agents with correct capabilities
- [ ] `resource://agents/{id}/state` works for local agents, errors for bridge agents
- [ ] `resource://agents/{id}/approvals/pending` returns pending approvals
- [ ] `resource://agents/{id}/approvals/history` returns historical timeline with Pydantic models
- [ ] `resource://agents/{id}/policy/proposals` returns policy proposals with URIs to policy server
- [ ] `resource://approvals/pending` returns `mcp_types.ReadResourceResult` with multiple `TextResourceContents` blocks
- [ ] Each content block (TextResourceContents) has uri, mimeType, and text (JSON-serialized approval)
- [ ] `approve_tool_call` routes to correct agent and approves
- [ ] `reject_tool_call` routes to correct agent and rejects
- [ ] `abort_agent` routes to correct agent and aborts
- [ ] Resource notifications fire when approvals change (both local and bridge agents)
- [ ] Resource notifications fire when agent state changes (both local and bridge agents)
- [ ] Resource notifications fire when history changes (both local and bridge agents)
- [ ] Historical timeline entries use Pydantic models throughout
- [ ] Test with 2+ agents (local and bridge)
- [ ] **Code quality**: No `getattr`, `hasattr`, or `setattr` - use proper attribute access
- [ ] **Code quality**: Everything typed properly - no `Any` types
- [ ] **Code quality**: No code smells flagged by any `prompts/scans/*.md` prompts
- [ ] **Code quality**: All imports at top of file, strictly - no exceptions for cyclical references (code written to avoid them)
- [ ] **Code quality**: Resource URLs are not duplicated - templates/constants defined in exactly one place

#### 1.3 Token Authentication

**File**: `adgn/src/adgn/agent/mcp_bridge/server.py`

```python
import secrets

class UITokenAuthMiddleware:
    """Token auth for Management UI."""

    def __init__(self, app, ui_token: str):
        self.app = app
        self.ui_token = ui_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode()

        if not auth.startswith("Bearer "):
            return await self._send_401(send)

        token = auth[7:]
        if token != self.ui_token:
            return await self._send_401(send)

        await self.app(scope, receive, send)

    async def _send_401(self, send):
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [[b"content-type", b"application/json"]],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"error": "unauthorized"}',
        })

def generate_ui_token() -> str:
    """Generate UI token (from env or random)."""
    import os
    if token := os.environ.get("UI_TOKEN"):
        return token
    return secrets.token_urlsafe(32)
```

**Acceptance**:
- [ ] Token loaded from `UI_TOKEN` env var if present
- [ ] Token generated randomly if env var not set
- [ ] Requests with valid token succeed
- [ ] Requests with invalid token get 401
- [ ] Requests with no token get 401

#### 1.4 Server Setup & CLI

**File**: `adgn/src/adgn/agent/mcp_bridge/cli.py`

```python
async def _run_server(...):
    # Generate UI token
    ui_token = generate_ui_token()

    # Create unified agents server
    agents_server = make_agents_server(registry)

    # Create UI app with token auth
    ui_app = create_management_ui_app(agents_server, ui_token)

    # Print Management UI URL with token
    ui_url = f"http://localhost:{ui_port}/ui?token={ui_token}"
    print(f"\n{'='*60}")
    print(f"Management UI: {ui_url}")
    print(f"{'='*60}\n")

    # Run servers
    await asyncio.gather(
        mcp_server.serve(),
        ui_server.serve()
    )
```

**Acceptance**:
- [ ] CLI prints Management UI URL with token
- [ ] Token is consistent across server lifetime
- [ ] Servers start successfully
- [ ] Can access UI at printed URL

### Phase 2: Frontend MCP Client

**No stub implementations** - full working frontend required.

#### 2.1 Install MCP SDK

```bash
cd adgn/src/adgn/agent/web
npm install @modelcontextprotocol/sdk
```

**Acceptance**:
- [ ] Package installed successfully
- [ ] TypeScript types available

#### 2.2 MCP Client Utilities

**File**: `adgn/src/adgn/agent/web/src/features/mcp/client.ts`

```typescript
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
      resources: { subscribe: true }  // Enable resource subscriptions
    }
  })

  await client.connect(transport)
  return client
}

// MCP SDK provides:
// - client.request({ method: 'resources/read', params: { uri } })
// - client.request({ method: 'resources/subscribe', params: { uri } })
// - client.request({ method: 'tools/call', params: { name, arguments } })
// - client.on('notification', handler)  // For resource update notifications
```

**Acceptance**:
- [ ] Client connects successfully with token
- [ ] Client can read resources
- [ ] Client can subscribe to resources
- [ ] Client receives notifications

#### 2.3 Token Management

**File**: `adgn/src/adgn/agent/web/src/features/auth/token.ts`

```typescript
const TOKEN_KEY = 'ducktape_ui_token'

export function getTokenFromURL(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get('token')
}

export function getTokenFromStorage(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function saveTokenToStorage(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch (e) {
    console.warn('Failed to save token to localStorage:', e)
  }
}

export function getToken(): string | null {
  // Priority: URL param > localStorage
  return getTokenFromURL() || getTokenFromStorage()
}

export function handleAuthFailure(): void {
  // Clear invalid token
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {}

  // Redirect to get new token (user must restart server)
  alert('Authentication failed. Please use the Management UI URL from server startup.')
}
```

**Acceptance**:
- [ ] Token extracted from URL on first load
- [ ] Token saved to localStorage
- [ ] Token retrieved from localStorage on subsequent loads
- [ ] Auth failure clears token and shows message

#### 2.4 Agents Client

**File**: `adgn/src/adgn/agent/web/src/features/agents/mcpClient.ts`

```typescript
import { createMCPClient } from '../mcp/client'
import { writable } from 'svelte/store'
import type { Client } from '@modelcontextprotocol/sdk/client/index.js'

export interface AgentInfo {
  agent_id: string
  capabilities: {
    chat: boolean
    agent_loop: boolean
  }
  mode: 'local' | 'bridge'
  state_uri?: string
  approvals_uri?: string
}

export const agentList = writable<AgentInfo[]>([])
export const globalApprovals = writable<any[]>([])

let agentsClient: Client | null = null

export async function connectAgents(token: string) {
  agentsClient = await createMCPClient({
    name: 'agents',
    url: 'http://localhost:8081/mcp/agents',
    token
  })

  // Initial fetch
  await refreshAgentList()
  await refreshGlobalApprovals()

  // Subscribe to updates
  await agentsClient.request({
    method: 'resources/subscribe',
    params: { uri: 'resource://agents/list' }
  })
  await agentsClient.request({
    method: 'resources/subscribe',
    params: { uri: 'resource://approvals/pending' }
  })

  // Listen for resource updates
  agentsClient.on('notification', async (notif: any) => {
    if (notif.method === 'notifications/resources/updated') {
      const uri = notif.params.uri
      if (uri === 'resource://agents/list') {
        await refreshAgentList()
      } else if (uri === 'resource://approvals/pending') {
        await refreshGlobalApprovals()
      } else if (uri.startsWith('resource://agents/') && uri.endsWith('/state')) {
        // State changed for specific agent - could refresh detail view
      }
    }
  })
}

async function refreshAgentList() {
  if (!agentsClient) return

  const result = await agentsClient.request({
    method: 'resources/read',
    params: { uri: 'resource://agents/list' }
  })

  const data = JSON.parse(result.contents[0].text)
  agentList.set(data.agents)
}

async function refreshGlobalApprovals() {
  if (!agentsClient) return

  const result = await agentsClient.request({
    method: 'resources/read',
    params: { uri: 'resource://approvals/pending' }
  })

  // Global mailbox returns multiple MCP content blocks (TextResourceContents)
  // Each content block is a separate approval with URI + inline JSON
  const approvals = result.contents.map((block: any) => {
    // block.uri: unique resource URI for this approval
    // block.text: inline JSON content with approval details
    const approval = JSON.parse(block.text)
    return {
      ...approval,
      uri: block.uri  // Keep the URI for reference/display
    }
  })
  globalApprovals.set(approvals)
}

export async function approveToolCall(agentId: string, callId: string) {
  if (!agentsClient) throw new Error('Not connected')

  await agentsClient.request({
    method: 'tools/call',
    params: {
      name: 'approve_tool_call',
      arguments: { agent_id: agentId, call_id: callId }
    }
  })
}

export async function rejectToolCall(agentId: string, callId: string, reason: string) {
  if (!agentsClient) throw new Error('Not connected')

  await agentsClient.request({
    method: 'tools/call',
    params: {
      name: 'reject_tool_call',
      arguments: { agent_id: agentId, call_id: callId, reason }
    }
  })
}

export async function abortAgent(agentId: string) {
  if (!agentsClient) throw new Error('Not connected')

  await agentsClient.request({
    method: 'tools/call',
    params: {
      name: 'abort_agent',
      arguments: { agent_id: agentId }
    }
  })
}

export async function getAgentHistory(agentId: string): Promise<any[]> {
  if (!agentsClient) throw new Error('Not connected')

  const result = await agentsClient.request({
    method: 'resources/read',
    params: { uri: `resource://agents/${agentId}/approvals/history` }
  })

  const data = JSON.parse(result.contents[0].text)
  return data.timeline  // Array of historical approval entries
}
```

**Acceptance**:
- [ ] Connects to agents server successfully
- [ ] Fetches agent list
- [ ] Fetches global approvals (handles multiple MCP content blocks from ReadResourceResult)
- [ ] Parses TextResourceContents blocks to extract individual approvals (each with URI + JSON)
- [ ] Fetches agent history timeline
- [ ] Subscribes to resource updates
- [ ] Receives notifications and refreshes data
- [ ] Pending approvals view live-updates when agents request approvals (local and bridge)
- [ ] Historical timeline view live-updates when decisions are made (local and bridge)
- [ ] `approveToolCall` works
- [ ] `rejectToolCall` works
- [ ] `abortAgent` works
- [ ] `getAgentHistory` returns timeline data

#### 2.5 UI Components

**File**: `adgn/src/adgn/agent/web/src/App.svelte`

```svelte
<script lang="ts">
  import { onMount } from 'svelte'
  import { getToken, handleAuthFailure } from './features/auth/token'
  import { connectAgents, agentList, globalApprovals } from './features/agents/mcpClient'

  let loading = true
  let error: string | null = null

  onMount(async () => {
    const token = getToken()
    if (!token) {
      error = 'No authentication token found. Please use the Management UI URL from server startup.'
      loading = false
      return
    }

    try {
      await connectAgents(token)
      loading = false
    } catch (e) {
      console.error('Failed to connect:', e)
      handleAuthFailure()
      error = 'Authentication failed'
      loading = false
    }
  })
</script>

{#if loading}
  <div>Loading...</div>
{:else if error}
  <div class="error">{error}</div>
{:else}
  <div class="app">
    <!-- Agent list, approvals UI, etc. -->
    <AgentList agents={$agentList} />
    <ApprovalsList approvals={$globalApprovals} />
  </div>
{/if}
```

**Acceptance**:
- [ ] Shows loading state on startup
- [ ] Extracts token from URL
- [ ] Connects to MCP server
- [ ] Displays agents and approvals
- [ ] Shows error on auth failure
- [ ] Displays active policy source code for each agent
- [ ] Allows user to edit and update active policy source code
- [ ] Displays policy proposals for each agent
- [ ] Links to individual proposal content in policy server

### Phase 3: Shared Models

**No stub implementations** - full type generation required.

#### 3.1 Install Generator

```bash
cd adgn/src/adgn/agent/web
npm install --save-dev pydantic-to-typescript
```

#### 3.2 Configure Generation

**File**: `adgn/src/adgn/agent/web/package.json`

```json
{
  "scripts": {
    "generate-types": "pydantic2ts --module adgn.agent.server.protocol --output src/types/protocol.ts",
    "prebuild": "npm run generate-types"
  }
}
```

#### 3.3 Export Pydantic Models

**File**: `adgn/src/adgn/agent/server/protocol.py`

Ensure all frontend-facing models are exported:
- **Request/response models**:
  - `PendingApproval` (approval details)
  - `ApprovalHistoryEntry` (historical timeline entry)
  - `AgentInfo` (agent metadata)
  - `AgentListResponse` (agents list)
  - `AgentApprovalsPendingResponse` (per-agent pending)
  - `AgentApprovalsHistoryResponse` (per-agent history)
  - `ApprovalContentBlock` (content block structure)
  - `GlobalApprovalsResponse` (global mailbox)
- **Tool schemas**:
  - `ApproveToolCallArgs`
  - `RejectToolCallArgs`
  - `AbortAgentArgs`
- **Legacy models** (if still needed):
  - `ApprovalBrief`
  - `ApprovalPendingEvt`
  - `ServerCapabilities`
  - `SamplingSnapshot`
  - `ServerEntry` (discriminated union)

**Acceptance**:
- [ ] `npm run generate-types` succeeds
- [ ] Generated TypeScript types match Pydantic models
- [ ] Frontend can import and use generated types
- [ ] Test type compatibility with actual API responses

### Phase 4: End-to-End Testing

**Full acceptance testing** - no incomplete features.

**Testing Strategy**:
- For local testing, mock out the OpenAI API using `unittest.mock` or `pytest-mock`. This avoids actual API calls and allows testing of infrastructure routing, approval flows, and UI integration without needing live LLM responses.
- Tests should **reuse common fixtures** to avoid duplication across test files
- Use **PyHamcrest matchers** for test assertions to avoid complex or duplicated matcher code

#### 4.1 Backend Tests

**File**: `adgn/tests/agent/mcp_bridge/test_agents_server.py`

```python
async def test_agents_server_basic():
    """Test unified agents server basic functionality."""
    # Setup: Create registry with 2 agents (1 local, 1 bridge)
    # Mock OpenAI API for local testing - no actual LLM calls needed
    registry = ...
    agents_server = make_agents_server(registry)

    # Connect MCP client
    client = ...

    # Test: List agents
    result = await client.read_resource("resource://agents/list")
    agents = json.loads(result.contents[0].text)["agents"]
    assert len(agents) == 2
    assert agents[0]["mode"] in ["local", "bridge"]

    # Test: Read local agent state
    local_agent = [a for a in agents if a["mode"] == "local"][0]
    state = await client.read_resource(local_agent["state_uri"])
    assert "ts" in state  # SamplingSnapshot

    # Test: Global approvals mailbox (multiple MCP content blocks)
    approvals_result = await client.read_resource("resource://approvals/pending")
    # Result.contents is list[TextResourceContents] - each is a separate approval
    assert len(approvals_result.contents) >= 0  # May be empty if no pending approvals
    # Verify each content block is a TextResourceContents with approval data
    for block in approvals_result.contents:
        assert isinstance(block, mcp_types.TextResourceContents)
        assert hasattr(block, "uri")  # Each block has its own URI
        assert block.mimeType == "application/json"
        approval = json.loads(block.text)
        assert "agent_id" in approval
        assert "call_id" in approval
        assert "tool" in approval
        assert "args" in approval

    # Test: Agent history timeline
    history_result = await client.read_resource(f"resource://agents/{local_agent['agent_id']}/approvals/history")
    history_data = json.loads(history_result.contents[0].text)
    assert "timeline" in history_data
    assert "count" in history_data
    # Verify history entry structure (Pydantic models)
    if history_data["timeline"]:
        entry = history_data["timeline"][0]
        assert "call_id" in entry
        assert "tool" in entry
        assert "decision" in entry
        assert entry["decision"] in ["approved", "rejected"]
        assert "timestamp" in entry
        assert "decided_by" in entry

    # Test: Approve tool call
    result = await client.call_tool("approve_tool_call", {
        "agent_id": "test_agent",
        "call_id": "test_call"
    })
    assert result["status"] == "approved"

async def test_resource_notifications():
    """Test resource update notifications."""
    # Setup
    registry = ...
    agents_server = make_agents_server(registry)
    client = ...

    # Subscribe to global approvals
    await client.subscribe_resource("resource://approvals/pending")

    # Trigger approval change
    # (via approval engine event)

    # Assert notification received
    # Assert resource updated

async def test_routing_to_agent_infrastructure():
    """Test tool routing to per-agent infrastructure."""
    # Setup with mock infrastructure
    # Call approve_tool_call(agent_id="foo", ...)
    # Verify called infra.approval_engine.approve()

async def test_abort_agent():
    """Test agent abort routing."""
    # Setup local agent
    # Call abort_agent(agent_id="foo")
    # Verify called infra.agent_loop.abort()

    # Test error for bridge agent
    # Call abort_agent(agent_id="bridge_agent")
    # Assert raises error

async def test_token_auth():
    """Test UI token authentication."""
    # Valid token: succeeds
    # Invalid token: 401
    # No token: 401

async def test_content_blocks_structure():
    """Test global approvals mailbox returns multiple MCP content blocks."""
    # Setup with multiple agents with pending approvals
    # Read resource://approvals/pending
    # Verify returns ReadResourceResult with contents: list[TextResourceContents]
    # Verify each block is TextResourceContents with uri, mimeType, text
    # Verify each text is valid JSON with approval details (agent_id, call_id, tool, args)

async def test_historical_timeline_pydantic():
    """Test historical timeline uses Pydantic models."""
    # Setup agent with approval history
    # Create ApprovalHistoryEntry instances via approval engine
    # Read resource://agents/{id}/approvals/history
    # Verify timeline entries match Pydantic schema
    # Verify timestamp is ISO format
    # Verify decision is literal "approved" or "rejected"
    # Verify decided_by is "human" or agent ID
```

**Acceptance**:
- [ ] All backend tests pass
- [ ] Resource reads work
- [ ] Tool calls route correctly
- [ ] Notifications fire correctly
- [ ] Auth works correctly
- [ ] Tests use PyHamcrest matchers for readable assertions
- [ ] Common fixtures are extracted and reused across test files

#### 4.2 Frontend Tests

**File**: `adgn/src/adgn/agent/web/src/features/agents/mcpClient.test.ts`

```typescript
describe('MCP Client', () => {
  it('connects with valid token', async () => {
    // Mock MCP server
    // Connect with token
    // Assert connected
  })

  it('fetches agent list', async () => {
    // Connect
    // Fetch agents
    // Assert correct data
  })

  it('approves tool call', async () => {
    // Connect
    // Call approveToolCall
    // Assert tool called with correct args
  })

  it('receives resource notifications', async () => {
    // Connect
    // Subscribe to resource
    // Trigger notification
    // Assert store updated
  })

  it('handles multiple MCP content blocks in global approvals', async () => {
    // Connect
    // Fetch resource://approvals/pending
    // Verify result.contents is array of TextResourceContents
    // Verify each block parsed correctly (has uri, mimeType, text)
    // Verify each approval has agent_id, call_id, tool, args
  })

  it('fetches agent history timeline', async () => {
    // Connect
    // Call getAgentHistory(agent_id)
    // Verify returns timeline array
    // Verify each entry has required fields (call_id, tool, decision, timestamp, decided_by)
  })
})
```

**Acceptance**:
- [ ] All frontend tests pass
- [ ] Client connects successfully
- [ ] Resources fetched correctly
- [ ] Tools called correctly
- [ ] Notifications received and handled

#### 4.3 Integration Tests

**File**: `adgn/tests/agent/mcp_bridge/test_e2e_integration.py`

```python
async def test_full_approval_flow():
    """End-to-end approval flow test."""
    # 1. Start server with agents
    # 2. Connect frontend client
    # 3. Trigger tool call (blocked by policy)
    # 4. Verify appears in global approvals
    # 5. Approve via frontend client
    # 6. Verify tool call proceeds
    # 7. Verify approval removed from pending

async def test_multi_agent_orchestration():
    """Test with multiple agents."""
    # 1. Create 3 agents (2 local, 1 bridge)
    # 2. Each agent has pending approvals
    # 3. Verify global mailbox shows all
    # 4. Approve from different agents
    # 5. Verify correct routing

async def test_agent_state_updates():
    """Test agent state change notifications."""
    # 1. Start local agent (idle)
    # 2. Subscribe to state
    # 3. Start agent loop (running)
    # 4. Verify notification received
    # 5. Abort agent
    # 6. Verify notification received
```

**Acceptance**:
- [ ] Full approval flow works end-to-end
- [ ] Multi-agent scenarios work
- [ ] State updates propagate correctly
- [ ] All integration tests pass

#### 4.4 Playwright End-to-End Tests

**Note**: The repository already has Playwright tests set up. The new Management UI should be covered by Playwright e2e tests.

**File**: `adgn/tests/e2e/test_management_ui.py` (or similar Playwright test file)

```python
async def test_management_ui_approval_flow(page):
    """Test approval flow through the UI."""
    # 1. Navigate to Management UI with token
    # 2. Verify agent list renders
    # 3. Verify global approvals mailbox shows pending
    # 4. Click approve on an approval
    # 5. Verify approval disappears from pending
    # 6. Verify appears in history timeline

async def test_management_ui_content_blocks(page):
    """Test global approvals MCP content blocks rendering."""
    # 1. Navigate to UI
    # 2. Verify each approval renders with correct data (from MCP TextResourceContents)
    # 3. Verify each approval shows its URI
    # 4. Verify inline content displays correctly (agent_id, tool, args)
    # 5. Verify live-updates when new approvals arrive (both local and bridge agents)

async def test_management_ui_realtime_updates(page):
    """Test real-time resource updates."""
    # 1. Navigate to UI
    # 2. Trigger approval change from backend
    # 3. Verify UI updates without refresh
    # 4. Verify notifications handled correctly

async def test_management_ui_agent_history(page):
    """Test historical timeline display."""
    # 1. Navigate to UI
    # 2. View agent detail page
    # 3. Verify history timeline renders
    # 4. Verify entries show decision, timestamp, decided_by
    # 5. Verify chronological ordering
```

**Acceptance**:
- [ ] Playwright tests cover full user workflows
- [ ] UI approval flow works end-to-end
- [ ] Content blocks render correctly
- [ ] Real-time updates work
- [ ] Historical timeline displays correctly
- [ ] All Playwright tests pass

### Phase 5: Migration & Cleanup

#### 5.1 Remove WebSocket Code

**Files to delete**:
- `/ws/policy` endpoint
- `/ws/approvals` endpoint
- `/ws/mcp` endpoint
- WebSocket test fixtures

**Acceptance**:
- [ ] All WebSocket code removed
- [ ] No dead code remains
- [ ] Tests updated to use MCP

#### 5.2 Documentation

Update docs:
- Architecture overview
- API reference for `agents` server
- Frontend integration guide
- Deployment guide

**Acceptance**:
- [ ] Documentation complete and accurate
- [ ] Examples work
- [ ] No outdated information

## Future: MCP Elicitations

### Elicitation-Based Approvals (Phase 6+)

**Why elicitations are perfect for approvals**:
- Standardized human-in-the-loop workflow
- 3-action model (accept/decline/cancel) built-in
- Client controls UX (native approval dialog)
- Server can't request PII/credentials (security)

**How it would work**:

```python
# Backend: Server sends elicitation
@server.elicitation()
async def request_approval(call_id: str, tool: str, args: dict):
    """Request user approval for tool call."""
    return {
        "type": "approval",
        "call_id": call_id,
        "tool": tool,
        "arguments": args,
        "schema": {
            "type": "object",
            "properties": {
                "approved": {"type": "boolean"},
                "reason": {"type": "string", "optional": True}
            }
        }
    }

# Frontend: Client receives elicitation
client.on('elicitation', async (request) => {
  // Show native approval dialog
  const result = await showApprovalDialog(request)

  // Respond with accept/decline/cancel
  await client.respondToElicitation(request.id, {
    action: result.approved ? 'accept' : 'decline',
    content: { approved: result.approved, reason: result.reason }
  })
})
```

**Migration path**:
1. Keep tool-based approvals (backward compat)
2. Add elicitation support to `agents` server
3. Frontend detects elicitation capability and uses it
4. Eventually deprecate tool-based approvals

## Success Metrics

### Phase 1 (Backend)
- [ ] Unified `agents` server implemented (no stubs)
- [ ] All resources work (`agents/list`, `agents/{id}/state`, `agents/{id}/approvals/pending`, `agents/{id}/approvals/history`, `approvals/pending`)
- [ ] All tools work (`approve_tool_call`, `reject_tool_call`, `abort_agent`)
- [ ] All data uses Pydantic models (no raw dicts)
- [ ] No exception swallowing (crashes on failure)
- [ ] Content blocks work correctly in global mailbox
- [ ] Historical timeline returns proper Pydantic models
- [ ] Resource notifications fire correctly
- [ ] Token auth works
- [ ] CLI prints Management UI URL with token
- [ ] All backend tests pass
- [ ] **Code quality**: No `getattr`, `hasattr`, or `setattr` - use proper attribute access
- [ ] **Code quality**: Everything typed properly - no `Any` types
- [ ] **Code quality**: No code smells flagged by `prompts/scans/*.md` prompts

### Phase 2 (Frontend)
- [ ] MCP SDK installed
- [ ] Client connects successfully
- [ ] Token management works (URL → localStorage)
- [ ] Agent list displays
- [ ] Global approvals mailbox displays (handles multiple MCP content blocks)
- [ ] Historical timeline displays
- [ ] Approve/reject/abort actions work
- [ ] **Live-update requirement**: Pending approvals view auto-updates as agents request approvals (both local and bridge agents)
- [ ] **Live-update requirement**: Historical timeline view auto-updates as decisions are made (both local and bridge agents)
- [ ] Notifications update UI in real-time
- [ ] All frontend tests pass

### Phase 3 (Shared Models)
- [ ] TypeScript types auto-generated from Pydantic
- [ ] Type compatibility validated
- [ ] No manual type duplication

### Phase 4 (Testing)
- [ ] All backend tests pass
- [ ] All frontend tests pass
- [ ] All integration tests pass
- [ ] All Playwright e2e tests pass
- [ ] End-to-end approval flow works
- [ ] Multi-agent scenarios work
- [ ] Content blocks rendering tested
- [ ] Historical timeline display tested
- [ ] Real-time updates tested via Playwright

### Phase 5 (Cleanup)
- [ ] WebSocket code removed
- [ ] Documentation complete
- [ ] No dead code
- [ ] No stub implementations

## Timeline Estimate

- **Phase 1** (Backend): 3-4 days
- **Phase 2** (Frontend): 2-3 days
- **Phase 3** (Shared Models): 1 day
- **Phase 4** (Testing): 2-3 days
- **Phase 5** (Cleanup): 1 day
- **Total**: ~2 weeks

## Future Enhancements (Beyond Phase 5)

These features would improve production deployment:

- [ ] **Idle Cleanup**: Auto-shutdown infrastructure after N minutes of inactivity per agent_id
- [ ] **Token Reload**: Hot-reload token mapping file without restart (watch file for changes)
- [ ] **Unified Instructions**: Merge server instructions in initialization message
- [ ] **Metrics**: Per-agent usage metrics (tool calls, approvals, policy evaluations)
- [ ] **MCP Elicitations**: Replace tool-based approvals with standardized elicitation workflow (Phase 6+)
- [ ] **SQLAlchemy Migration**: Migrate from raw aiosqlite to SQLAlchemy ORM for better type safety and migrations
- [ ] **Remove SidecarBundle**: Eliminate SidecarBundle abstraction - currently a no-op for external agents, adds unnecessary complexity

## References

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-06-18/)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Elicitations](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation)
- [Streamable HTTP Transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
