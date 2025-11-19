# MCP-Based Management UI - Unified "agents" Server

## Executive Summary

Replace custom WebSocket channels with a unified **`agents` MCP server** that provides cross-agent management. This single server routes to per-agent infrastructure and can be delegated to other agents for self-orchestration. The frontend becomes a simple MCP client, and the same server can later be given to agents for spawning, approving, and managing other agents.

**Important**: This implementation may break backward compatibility with previous versions. Breaking changes are acceptable to achieve a cleaner architecture and better type safety.

## Key Decisions

### Type Organization
**Decision**: New persistence types (`Decision`, `ToolCallExecution`, `ToolCallRecord`) will live in `adgn/src/adgn/agent/persist/__init__.py` alongside `ApprovalRecord`. This keeps persistence models together.

### Type Consolidation
**Decision**: Keep two `ToolCall` types (Option B):
- Simple `ToolCall` in `approvals.py` (renamed from `ApprovalToolCall`) - for persistence/approvals
- Discriminated `ToolCall` in `protocol.py` (with `type` field) - for wire protocol
- TODO: Reconsider if this becomes confusing

### Policy Proposals UI Access
**Decision**: Frontend directly uses existing policy server resources (Option B). No routing through agents server. The policy server already exposes proposals resources that work correctly.

### Agents Server Pattern
**Decision**: Follow compositor pattern - `agents` server should be a FastMCP proxy doing translation/routing to per-agent MCP servers. This avoids duplicating routing logic 500 times.

### Database Migration Strategy
**Decision**: Drop and recreate databases (Option B). Document that existing approval history will be lost. Acceptable for personal infrastructure during development phase.

## Known Gaps & Future Work

This plan focuses on **core approval and timeline functionality**. The following features are mentioned in mockups/API but are **out of scope** for initial phases:

**Out of Scope (Phase 1-5)**:
- Policy proposals resource (`resource://agents/{id}/policy/proposals`) - Policy server handles this
- UI server blocks resource (`resource://ui/{id}/blocks`) - Will be integrated when UI server is attached
- `send_message` tool - Only needed when UI server is attached
- Policy editor UI component - Will reuse existing policy server resources

**Clarifications**:
- `AgentMode` already exists in `adgn/src/adgn/agent/mcp_bridge/types.py` - import it, don't redefine
- `ToolCallEntry` (timeline display model) vs `ToolCallRecord` (persistence model) serve different purposes
- Breaking backward compatibility is acceptable for cleaner architecture

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

### MCP API

**Resources:**
```typescript
// Core agent info
resource://agents/list
  → { agents: AgentInfo[] }

// Policy gate timeline (ALWAYS available, both agent types)
resource://agents/{id}/approvals/history
  → { timeline: ToolCallEntry[], pending: PendingApproval[] }

// Active policy
resource://approval-policy/policy.py
  → Python source code (string)

// Policy proposals
resource://agents/{id}/policy/proposals
  → { proposals: PolicyProposalInfo[], active_policy_uri: string }

// UI server blocks (OPTIONAL - only if UI server attached)
resource://ui/{id}/blocks
  → { blocks: UIBlock[] }

// Agent state (for sidebar badges)
resource://agents/{id}/state
  → { agent_id: string, state: "waiting_approval" | "executing" | "sampling" | "idle" }
```

**Tools:**
```typescript
approve_tool_call(agent_id, call_id) → void
reject_tool_call(agent_id, call_id, reason) → void
abort_agent(agent_id) → void  // Only for local agents
send_message(agent_id, content) → void  // Only if UI server attached
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

### Phase 0 (Type Consolidation & Data Models)
- [ ] `ApprovalToolCall` renamed to `ToolCall` in `approvals.py`
- [ ] All imports updated (middleware, persistence, plan)
- [ ] New persistence models defined (`Decision`, `ToolCallExecution`, `ToolCallRecord`)
- [ ] Database schema updated with new columns
- [ ] Migration strategy documented
- [ ] Middleware bugs fixed (USER outcomes recorded correctly)
- [ ] Tool arguments passed to `record_approval()` calls
- [ ] Execution tracking implemented (start/completion)
- [ ] All component tests pass (A-E)
- [ ] All verification tasks pass (V1-V5, V-final)
- [ ] Integration tests pass (full approval lifecycle)
- [ ] Type checking passes (mypy)
- [ ] Code coverage ≥80% for new code
- [ ] No code smells flagged by `prompts/scans/*.md`

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
- [ ] **Data model refactors**: All TODOs from "Data Model Improvements & Bug Fixes" section completed:
  - [ ] Fixed middleware bug (USER outcomes recorded correctly, not as POLICY outcomes)
  - [ ] Tool arguments passed to `record_approval()` calls
  - [ ] Execution start/completion tracked in middleware
  - [ ] Typed fields added to persistence (Decision, ToolCallExecution models)
  - [ ] Database schema updated for new fields
  - [ ] `list_approvals()` returns enriched ToolCallRecord models
  - [ ] ApprovalRecord renamed to ToolCallRecord (or kept with clear rationale)

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

## Implementation Phases

### Phase 0: Type Consolidation & Data Models (Foundation)

**Purpose**: Clean up type system and create foundation for persistence improvements.

**Timeline**: 1-2 days (highly parallelizable)

#### Dependency Graph

```
Group 1 (Fully Parallel):
├─ Task A: Rename ApprovalToolCall → ToolCall
└─ Task B: Define persistence models

Group 2 (Depends on Group 1):
├─ Task C: Update database schema (needs B)
└─ Task D: Fix middleware bugs (needs A)

Group 3 (Depends on Group 2):
└─ Task E: Track execution in middleware (needs A, B, C, D)

Verification (Parallel after dependencies):
├─ Task V1: Verify type consolidation (after A)
├─ Task V2: Verify persistence models (after B)
├─ Task V3: Verify database schema (after C)
├─ Task V4: Verify middleware bugs (after D)
├─ Task V5: Verify execution tracking (after E)
└─ Task V-final: Integration verification (after all)
```

#### Task A: Rename ApprovalToolCall → ToolCall

**Dependencies**: None

**Files**:
- `adgn/src/adgn/agent/approvals.py`: Rename class
- `adgn/src/adgn/mcp/policy_gateway/middleware.py`: Update imports
- `adgn/src/adgn/agent/persist/__init__.py`: Update imports
- `plan.md`: Update references

**Definition of Done**:
- [ ] `ApprovalToolCall` renamed to `ToolCall` in `approvals.py`
- [ ] All imports updated in middleware, persistence
- [ ] No import errors when importing `ToolCall` from `approvals`
- [ ] No conflicts with `protocol.py` version (different modules)
- [ ] TODO added to reconsider if dual names become confusing
- [ ] **Tests**: All existing tests pass with renamed type
- [ ] **Tests**: Import test verifies both ToolCall types can coexist

#### Task B: Define Persistence Models

**Dependencies**: None

**Files**:
- `adgn/src/adgn/agent/persist/__init__.py`: Add new models

**Definition of Done**:
- [ ] `Decision` model defined with fields: `outcome: ApprovalOutcome`, `decided_at: datetime`, `reason: str | None`
- [ ] `ToolCallExecution` model defined with fields: `completed_at: datetime`, `output: mcp_types.CallToolResult`
- [ ] `ToolCallRecord` model defined with fields: `call_id`, `run_id`, `agent_id`, `tool_call: ToolCall`, `decision: Decision | None`, `execution: ToolCallExecution | None`
- [ ] All models are Pydantic BaseModel subclasses
- [ ] All fields properly typed (no `Any`)
- [ ] Docstrings explain "jointly optional" pattern
- [ ] TODO comment on ApprovalRecord about eventual deprecation
- [ ] **Tests**: Pydantic model validation tests (valid/invalid inputs)
- [ ] **Tests**: Test jointly optional pattern (decision=None, execution=None valid)
- [ ] **Tests**: Test serialization/deserialization (to/from JSON)

#### Task C: Update Database Schema

**Dependencies**: Task B (needs model definitions)

**Files**:
- `adgn/src/adgn/agent/persist/sqlite.py`: Schema updates
- Migration documentation

**Definition of Done**:
- [ ] New tables/columns for `ToolCallRecord` fields
- [ ] Columns for tool_call: `tool_name`, `tool_args_json`
- [ ] Columns for decision: `decision_outcome`, `decided_at`, `decision_reason`
- [ ] Columns for execution: `execution_completed_at`, `execution_output_json`
- [ ] Migration strategy documented: "Drop old tables, create new. Approval history will be lost."
- [ ] Schema version incremented
- [ ] **Tests**: Test database creation with new schema
- [ ] **Tests**: Test inserting ToolCallRecord instances
- [ ] **Tests**: Test querying ToolCallRecord instances
- [ ] **Tests**: Test NULL handling for optional decision/execution
- [ ] **Tests**: Test migration from scratch (fresh DB)

#### Task D: Fix Middleware Bugs

**Dependencies**: Task A (needs renamed ToolCall type)

**Files**:
- `adgn/src/adgn/mcp/policy_gateway/middleware.py`: Lines 242, 254, and record_approval calls

**Definition of Done**:
- [ ] Line 242: USER approvals recorded as `USER_APPROVE` (not `POLICY_ALLOW`)
- [ ] Line 254: USER rejections recorded as `USER_DENY_ABORT` (not `POLICY_DENY_ABORT`)
- [ ] Tool args passed to all `record_approval()` calls
- [ ] Middleware imports `ToolCall` from `approvals` (not `protocol`)
- [ ] **Tests**: Test USER approval recorded with correct outcome
- [ ] **Tests**: Test USER rejection recorded with correct outcome
- [ ] **Tests**: Test POLICY approval still works correctly
- [ ] **Tests**: Test tool args are captured in approval records
- [ ] **Tests**: Integration test: approval flow end-to-end

#### Task E: Track Execution in Middleware

**Dependencies**: Tasks A, B, C, D (needs types, schema, and bug fixes)

**Files**:
- `adgn/src/adgn/mcp/policy_gateway/middleware.py`: Execution tracking

**Definition of Done**:
- [ ] Track execution start: use `decision.decided_at` (no separate field needed)
- [ ] Track execution completion: capture timestamp after `call_next()`
- [ ] Capture tool output from `call_next()` result
- [ ] Pass execution data to persistence layer
- [ ] Handle execution errors gracefully
- [ ] **Tests**: Test execution completion captured
- [ ] **Tests**: Test execution output saved correctly
- [ ] **Tests**: Test timing: decided_at < completed_at
- [ ] **Tests**: Test error handling during tool execution
- [ ] **Tests**: Integration test: full lifecycle (pending → decided → executing → completed)

#### Task V1-V5: Component Verification

**Dependencies**: Each depends on corresponding task (A-E)

**Definition of Done for Each**:
- [ ] Run component-specific tests
- [ ] Check code quality (no `getattr`/`hasattr`/`setattr`, proper typing)
- [ ] Verify matches plan.md specification
- [ ] Check for code smells per `prompts/scans/*.md`

#### Task V-final: Integration Verification

**Dependencies**: All tasks A-E complete

**Definition of Done**:
- [ ] All component tests pass
- [ ] Integration tests pass (full approval lifecycle)
- [ ] Type checking passes (mypy)
- [ ] No regressions in existing functionality
- [ ] Code coverage for new code ≥80%
- [ ] Documentation updated
- [ ] Phase 0 checklist in Success Metrics section fully checked

### Execution Plan: Maximal Parallelism via Task Delegation

**Strategy**: Use Task tool to delegate work with maximum parallelism, then verify.

#### Wave 1: Parallel Foundation Tasks
Launch **2 agents in parallel** (single message with multiple Task calls):

```
Agent 1: Task A (Rename ApprovalToolCall → ToolCall)
  Prompt: "Rename ApprovalToolCall to ToolCall in adgn/src/adgn/agent/approvals.py.
          Update all imports in middleware.py and persist/__init__.py.
          Update references in plan.md.
          Add TODO comment about reconsidering dual names.
          Run existing tests to ensure no regressions.
          Add import coexistence test.
          Return summary of files changed and test results."

Agent 2: Task B (Define Persistence Models)
  Prompt: "Define new persistence models in adgn/src/adgn/agent/persist/__init__.py:
          - Decision(outcome: ApprovalOutcome, decided_at: datetime, reason: str | None)
          - ToolCallExecution(completed_at: datetime, output: CallToolResult)
          - ToolCallRecord(call_id, run_id, agent_id, tool_call, decision, execution)
          Use Pydantic BaseModel. Add docstrings explaining jointly optional pattern.
          Add TODO on ApprovalRecord about deprecation.
          Write validation tests, serialization tests, jointly optional tests.
          Return model definitions and test results."
```

**Wait for Wave 1 completion**, then:

#### Wave 2: Parallel Dependent Tasks
Launch **3 agents in parallel**:

```
Agent 3: Task C (Update Database Schema)
  Dependencies: Agent 2 output (model definitions)
  Prompt: "Update database schema in adgn/src/adgn/agent/persist/sqlite.py for ToolCallRecord.
          Add columns: tool_name, tool_args_json, decision_outcome, decided_at, decision_reason,
          execution_completed_at, execution_output_json.
          Document migration strategy: drop old tables, create new.
          Increment schema version.
          Write tests: DB creation, insert, query, NULL handling, fresh migration.
          Return schema changes and test results."

Agent 4: Task D (Fix Middleware Bugs)
  Dependencies: Agent 1 output (ToolCall rename)
  Prompt: "Fix middleware bugs in adgn/src/adgn/mcp/policy_gateway/middleware.py:
          - Line 242: Record USER_APPROVE (not POLICY_ALLOW)
          - Line 254: Record USER_DENY_ABORT (not POLICY_DENY_ABORT)
          - Pass tool args to all record_approval() calls
          - Import ToolCall from approvals (not protocol)
          Write tests: USER approval outcome, USER rejection outcome, POLICY approval,
          tool args captured, end-to-end approval flow.
          Return changes and test results."

Agent 5: Task V1 (Verify Task A)
  Dependencies: Agent 1 output
  Prompt: "Verify Task A completion:
          - Check ApprovalToolCall renamed in approvals.py
          - Check all imports updated
          - Run import coexistence test
          - Check for code smells (no getattr/hasattr/setattr)
          - Verify proper typing (mypy)
          Return verification report."
```

**Wait for Wave 2 completion**, then:

#### Wave 3: Parallel Execution & Verification
Launch **4 agents in parallel**:

```
Agent 6: Task E (Track Execution in Middleware)
  Dependencies: Agents 1, 2, 3, 4 outputs
  Prompt: "Add execution tracking to middleware.py:
          - Track start: use decision.decided_at (no separate field)
          - Track completion: capture timestamp after call_next()
          - Capture tool output from result
          - Pass execution data to persistence
          - Handle errors gracefully
          Write tests: completion captured, output saved, timing validation,
          error handling, full lifecycle test.
          Return changes and test results."

Agent 7: Task V2 (Verify Task B)
  Dependencies: Agent 2 output
  Prompt: "Verify Task B completion: Check models defined correctly,
          run validation tests, check code quality. Return verification report."

Agent 8: Task V3 (Verify Task C)
  Dependencies: Agent 3 output
  Prompt: "Verify Task C completion: Check schema updated correctly,
          run DB tests, verify migration docs. Return verification report."

Agent 9: Task V4 (Verify Task D)
  Dependencies: Agent 4 output
  Prompt: "Verify Task D completion: Check bugs fixed, test outcomes correct,
          run middleware tests. Return verification report."
```

**Wait for Wave 3 completion**, then:

#### Wave 4: Final Verification
Launch **2 agents in parallel**:

```
Agent 10: Task V5 (Verify Task E)
  Dependencies: Agent 6 output
  Prompt: "Verify Task E completion: Check execution tracking works,
          run lifecycle tests, verify error handling. Return verification report."

Agent 11: Task V-final (Integration Verification)
  Dependencies: All agents 1-10 outputs
  Prompt: "Run integration verification:
          - All component tests pass
          - Integration tests pass (full approval lifecycle)
          - Type checking passes (mypy)
          - No regressions
          - Code coverage ≥80%
          - Documentation updated
          - Phase 0 checklist complete
          Return comprehensive verification report with all metrics."
```

**Total agents**: 11 (max 4 concurrent)
**Total waves**: 4
**Estimated time**: 4-6 hours (vs 1-2 days sequential)

### Phase 1-5: (Previous Plan)

See detailed sections below for Phases 1-5 (Backend, Frontend, Shared Models, Testing, Cleanup).

## Parallel Execution Strategy

### Overview

This section maps out the complete parallel execution strategy for implementing the MCP-based Management UI, from Phase 0 (foundation) through Phase 5 (cleanup).

**Total estimated time with parallelism**: ~7-9 days (vs ~17-20 days sequential)

### Execution Waves

#### PHASE 0: Type Consolidation & Data Models (4-6 hours)

##### Wave 0.1 (2 parallel agents)
```
Agent 0.1.A: Rename ApprovalToolCall → ToolCall
Agent 0.1.B: Define persistence models (Decision, ToolCallExecution, ToolCallRecord)
```

##### Wave 0.2 (3 parallel agents)
**Depends on**: Wave 0.1 complete
```
Agent 0.2.C: Update database schema (needs 0.1.B)
Agent 0.2.D: Fix middleware bugs (needs 0.1.A)
Agent 0.2.V1: Verify Task A (needs 0.1.A)
```

##### Wave 0.3 (4 parallel agents)
**Depends on**: Wave 0.2 complete
```
Agent 0.3.E: Track execution in middleware (needs 0.1.A, 0.1.B, 0.2.C, 0.2.D)
Agent 0.3.V2: Verify Task B (needs 0.1.B)
Agent 0.3.V3: Verify Task C (needs 0.2.C)
Agent 0.3.V4: Verify Task D (needs 0.2.D)
```

##### Wave 0.4 (2 parallel agents)
**Depends on**: Wave 0.3 complete
```
Agent 0.4.V5: Verify Task E (needs 0.3.E)
Agent 0.4.V-final: Integration verification (needs all 0.1-0.3)
```

##### Wave 0.5 (Code quality scans - parallel)
**Depends on**: Wave 0.4 complete
```
Agent 0.5.Q1: Scan for getattr/hasattr/setattr usage
Agent 0.5.Q2: Scan for Any types
Agent 0.5.Q3: Scan for code smells (prompts/scans/*.md)
Agent 0.5.Q4: Run mypy type checking
Agent 0.5.Q5: Check code coverage ≥80%
```

---

#### PHASE 1: Backend (3-4 days)

##### Wave 1.1 (4 parallel agents)
**Depends on**: Phase 0 complete
```
Agent 1.1.A: Infrastructure Registry Enhancement
  - Add known_agents() method
  - Add get_infrastructure() method
  - Add get_agent_mode() method
  - Add get_local_runtime() method
  - Tests: multiple agents, mode detection, routing

Agent 1.1.B: Token Authentication
  - UITokenAuthMiddleware implementation
  - generate_ui_token() from env or random
  - Token validation logic
  - Tests: valid/invalid/missing tokens

Agent 1.1.C: Agent State Models
  - PendingApproval model
  - ApprovalHistoryEntry model
  - AgentInfo model
  - All response models for resources
  - Tests: Pydantic validation, serialization

Agent 1.1.D: Approval Engine Integration
  - get_pending() → list[PendingApproval]
  - get_history() → list[ApprovalHistoryEntry]
  - Update persistence to use ToolCallRecord
  - Tests: pending/history retrieval
```

##### Wave 1.2 (3 parallel agents)
**Depends on**: Wave 1.1 complete
```
Agent 1.2.A: Agents Server - Resources (Part 1)
  - resource://agents/list
  - resource://agents/{id}/state
  - resource://agents/{id}/approvals/pending
  - Uses models from 1.1.C, routing from 1.1.A
  - Tests: resource reads, routing, error handling

Agent 1.2.B: Agents Server - Resources (Part 2)
  - resource://agents/{id}/approvals/history
  - resource://approvals/pending (global mailbox)
  - Multi-content-block ReadResourceResult
  - Tests: history timeline, global mailbox format

Agent 1.2.C: Agents Server - Tools
  - approve_tool_call(agent_id, call_id)
  - reject_tool_call(agent_id, call_id, reason)
  - abort_agent(agent_id)
  - Tests: tool routing, error handling, local vs bridge
```

##### Wave 1.3 (2 parallel agents)
**Depends on**: Wave 1.2 complete
```
Agent 1.3.A: Resource Notifications
  - Wire up approval engine listeners
  - Wire up agent state listeners
  - broadcast_resource_updated() calls
  - Tests: notifications fire correctly

Agent 1.3.B: CLI Integration
  - Update CLI to create agents server
  - Print Management UI URL with token
  - Server startup integration
  - Tests: CLI output, server startup
```

##### Wave 1.4 (Verification - 3 parallel agents)
**Depends on**: Wave 1.3 complete
```
Agent 1.4.V1: Backend Integration Tests
  - Multi-agent scenarios
  - Approval flow end-to-end
  - Resource subscriptions

Agent 1.4.V2: Code Quality Scans
  - No getattr/hasattr/setattr
  - No Any types
  - Type checking passes

Agent 1.4.V3: API Contract Verification
  - All resources return correct Pydantic models
  - All tools have proper signatures
  - Global mailbox returns TextResourceContents
```

---

#### PHASE 2: Frontend (2-3 days)

**Note**: Can start Wave 2.1 once Wave 1.2 completes (basic resources available)

##### Wave 2.1 (3 parallel agents)
**Depends on**: Wave 1.2.A complete (basic resources)
```
Agent 2.1.A: Install & Configure MCP SDK
  - npm install @modelcontextprotocol/sdk
  - MCP client utilities (createMCPClient)
  - Streamable HTTP transport
  - Tests: client connection

Agent 2.1.B: Token Management
  - getTokenFromURL()
  - getTokenFromStorage()
  - saveTokenToStorage()
  - handleAuthFailure()
  - Tests: token extraction, storage

Agent 2.1.C: Base UI Structure
  - App.svelte skeleton
  - Loading/error states
  - Route structure
  - Tests: component rendering
```

##### Wave 2.2 (3 parallel agents)
**Depends on**: Wave 2.1 complete, Wave 1.2.B complete (history resource)
```
Agent 2.2.A: Agents Client (Core)
  - connectAgents()
  - agentList store
  - refreshAgentList()
  - Resource subscriptions
  - Tests: connection, list fetch, subscriptions

Agent 2.2.B: Agents Client (Approvals)
  - globalApprovals store
  - refreshGlobalApprovals()
  - approveToolCall(), rejectToolCall()
  - getAgentHistory()
  - Tests: approval operations, history fetch

Agent 2.2.C: Agents Client (Agent Ops)
  - abortAgent()
  - Agent state subscriptions
  - Notification handling
  - Tests: abort, state updates
```

##### Wave 2.3 (4 parallel agents)
**Depends on**: Wave 2.2 complete
```
Agent 2.3.A: Agent List Component
  - Sidebar with agent list
  - State badges (color-coded)
  - Agent selection
  - Tests: rendering, state badges

Agent 2.3.B: Timeline Component
  - Tool call timeline display
  - Merge policy gate + UI blocks
  - Chronological ordering
  - Tests: timeline rendering, merging

Agent 2.3.C: Approvals Component
  - Global approvals mailbox
  - Pending approval cards
  - Approve/Reject actions
  - Tests: approval UI, actions

Agent 2.3.D: Policy Editor Component
  - Policy source display
  - Uses existing policy server resources
  - Policy proposals display
  - Tests: policy display, proposals
```

##### Wave 2.4 (Verification - 2 parallel agents)
**Depends on**: Wave 2.3 complete
```
Agent 2.4.V1: Frontend Integration Tests
  - Full UI workflows
  - Real-time updates
  - Error handling

Agent 2.4.V2: Code Quality
  - TypeScript compilation
  - Linting
  - No console errors
```

---

#### PHASE 3: Shared Models (1 day)

##### Wave 3.1 (2 parallel agents)
**Depends on**: Wave 1.2 complete (backend models stable)
```
Agent 3.1.A: Install & Configure Generator
  - npm install pydantic-to-typescript
  - Configure package.json scripts
  - Set up prebuild hook

Agent 3.1.B: Export Pydantic Models
  - Ensure all models in protocol.py
  - Export approval models
  - Export response models
  - Export tool input/output schemas
```

##### Wave 3.2 (2 parallel agents)
**Depends on**: Wave 3.1 complete
```
Agent 3.2.A: Generate Types
  - Run pydantic2ts
  - Verify generated types
  - Fix any generation issues

Agent 3.2.B: Update Frontend Imports
  - Replace manual types with generated
  - Update all component imports
  - Verify type compatibility
```

##### Wave 3.3 (Verification - 1 agent)
**Depends on**: Wave 3.2 complete
```
Agent 3.3.V1: Type Compatibility Verification
  - TypeScript compilation passes
  - Runtime type checks
  - API response validation
```

---

#### PHASE 4: Testing (2-3 days)

**Note**: Different test suites can run in parallel once their dependencies are met

##### Wave 4.1 (4 parallel agents)
**Depends on**: Phases 1, 2, 3 complete
```
Agent 4.1.A: Backend Unit Tests
  - All backend components
  - Mock dependencies
  - Edge cases

Agent 4.1.B: Frontend Unit Tests
  - All UI components
  - Mock MCP client
  - User interactions

Agent 4.1.C: Integration Tests
  - Backend + Frontend
  - Multi-agent scenarios
  - Full approval workflows

Agent 4.1.D: Playwright E2E Tests (Part 1)
  - Management UI basic flows
  - Agent list navigation
  - Approval actions
```

##### Wave 4.2 (3 parallel agents)
**Depends on**: Wave 4.1 complete
```
Agent 4.2.A: Playwright E2E Tests (Part 2)
  - Real-time updates
  - Content blocks rendering
  - Error handling

Agent 4.2.B: Performance Tests
  - Multi-agent load
  - Resource notification performance
  - Frontend rendering performance

Agent 4.2.C: Security Tests
  - Token authentication
  - Authorization checks
  - Input validation
```

##### Wave 4.3 (Verification - 2 parallel agents)
**Depends on**: Wave 4.2 complete
```
Agent 4.3.V1: Test Coverage Analysis
  - Backend coverage ≥80%
  - Frontend coverage ≥80%
  - Integration coverage report

Agent 4.3.V2: Test Results Consolidation
  - All test suites pass
  - No flaky tests
  - Performance benchmarks met
```

---

#### PHASE 5: Cleanup (1 day)

##### Wave 5.1 (3 parallel agents)
**Depends on**: All tests pass (Phase 4 complete)
```
Agent 5.1.A: Remove WebSocket Endpoints
  - Delete /ws/policy
  - Delete /ws/approvals
  - Delete /ws/mcp
  - Remove WebSocket test fixtures

Agent 5.1.B: Update Documentation
  - Architecture docs
  - API reference
  - Deployment guide
  - Migration guide

Agent 5.1.C: Code Cleanup
  - Remove dead code
  - Remove commented code
  - Remove debug logging
  - Clean up imports
```

##### Wave 5.2 (Verification - 1 agent)
**Depends on**: Wave 5.1 complete
```
Agent 5.2.V1: Final Verification
  - All tests still pass
  - No dead code
  - Documentation complete
  - No stub implementations
```

---

#### PHASE FINAL: Comprehensive Code Quality Enforcement (4-6 hours)

**Note**: Runs after Phase 5 complete. Applies all code quality standards to entire adgn codebase.

##### Wave FINAL.1 (28 parallel agents - Scan & Report)
**Depends on**: Phase 5 complete
```
Agent F.1: Scan walrus-get-pattern
  Prompt: "Run prompts/scans/walrus-get-pattern.md over all adgn/ code.
          Report all violations found. Do not fix yet, just report."

Agent F.2: Scan useless-test-classes
  Prompt: "Run prompts/scans/useless-test-classes.md over all adgn/ code.
          Report all violations found."

Agent F.3: Scan useless-documentation
  Prompt: "Run prompts/scans/useless-documentation.md over all adgn/ code.
          Report all violations found."

Agent F.4: Scan unnecessary-verbosity
  Prompt: "Run prompts/scans/unnecessary-verbosity.md over all adgn/ code.
          Report all violations found."

Agent F.5: Scan useless-comments-and-docs
  Prompt: "Run prompts/scans/useless-comments-and-docs.md over all adgn/ code.
          Report all violations found."

Agent F.6: Scan timestamp-naming
  Prompt: "Run prompts/scans/timestamp-naming.md over all adgn/ code.
          Report all violations found."

Agent F.7: Scan type-ignore-suppressions
  Prompt: "Run prompts/scans/type-ignore-suppressions.md over all adgn/ code.
          Report all violations found."

Agent F.8: Scan trivial-forwarders
  Prompt: "Run prompts/scans/trivial-forwarders.md over all adgn/ code.
          Report all violations found."

Agent F.9: Scan trivial-forwarder-methods
  Prompt: "Run prompts/scans/trivial-forwarder-methods.md over all adgn/ code.
          Report all violations found."

Agent F.10: Scan suspicious-nullability
  Prompt: "Run prompts/scans/suspicious-nullability.md over all adgn/ code.
          Report all violations found."

Agent F.11: Scan stringly-typed
  Prompt: "Run prompts/scans/stringly-typed.md over all adgn/ code.
          Report all violations found."

Agent F.12: Scan suspicious-defaults
  Prompt: "Run prompts/scans/suspicious-defaults.md over all adgn/ code.
          Report all violations found."

Agent F.13: Scan test-assertions
  Prompt: "Run prompts/scans/test-assertions.md over all adgn/ code.
          Report all violations found."

Agent F.14: Scan pygit2-patterns
  Prompt: "Run prompts/scans/pygit2-patterns.md over all adgn/ code.
          Report all violations found."

Agent F.15: Scan pytest-tmp-paths
  Prompt: "Run prompts/scans/pytest-tmp-paths.md over all adgn/ code.
          Report all violations found."

Agent F.16: Scan pydantic-antipatterns
  Prompt: "Run prompts/scans/pydantic-antipatterns.md over all adgn/ code.
          Report all violations found."

Agent F.17: Scan manual-serde-needs-pydantic
  Prompt: "Run prompts/scans/manual-serde-needs-pydantic.md over all adgn/ code.
          Report all violations found."

Agent F.18: Scan methods-vs-freestanding
  Prompt: "Run prompts/scans/methods-vs-freestanding.md over all adgn/ code.
          Report all violations found."

Agent F.19: Scan mypy-appeasing-code
  Prompt: "Run prompts/scans/mypy-appeasing-code.md over all adgn/ code.
          Report all violations found."

Agent F.20: Scan overly-loose-typing
  Prompt: "Run prompts/scans/overly-loose-typing.md over all adgn/ code.
          Report all violations found."

Agent F.21: Scan functional-over-imperative
  Prompt: "Run prompts/scans/functional-over-imperative.md over all adgn/ code.
          Report all violations found."

Agent F.22: Scan library-type-misuse
  Prompt: "Run prompts/scans/library-type-misuse.md over all adgn/ code.
          Report all violations found."

Agent F.23: Scan duplicated-test-code
  Prompt: "Run prompts/scans/duplicated-test-code.md over all adgn/ code.
          Report all violations found."

Agent F.24: Scan denormalized-computed-fields
  Prompt: "Run prompts/scans/denormalized-computed-fields.md over all adgn/ code.
          Report all violations found."

Agent F.25: Scan api-model-design
  Prompt: "Run prompts/scans/api-model-design.md over all adgn/ code.
          Report all violations found."

Agent F.26: Scan asyncio-antipatterns
  Prompt: "Run prompts/scans/asyncio-antipatterns.md over all adgn/ code.
          Report all violations found."

Agent F.27: Scan identifier-naming
  Prompt: "Run prompts/scans/identifier-naming.md over all adgn/ code.
          Report all violations found."

Agent F.28: Scan fastmcp-documentation-patterns
  Prompt: "Run prompts/scans/fastmcp-documentation-patterns.md over all adgn/ code.
          Report all violations found."
```

##### Wave FINAL.2 (Consolidation & Parallelization Strategy - 1 agent)
**Depends on**: Wave FINAL.1 complete
```
Agent F.CONSOLIDATE: Consolidate Violations & Design Fix Strategy
  Prompt: "Review all 28 scan reports from Wave FINAL.1.

          1. Consolidate violations with priority:
             - Critical: Type safety, async correctness, API design
             - High: Code clarity, maintainability
             - Medium: Naming, documentation
             - Low: Style preferences

          2. Analyze overlap: Which files have violations from multiple scans?

          3. Propose parallelization strategy:
             Option A: By component/module (e.g., one agent for persist/, one for mcp/, etc.)
             Option B: By file/file-group (to avoid agents stepping on each other)
             Option C: By violation type (may cause conflicts)

          4. Recommend specific agent assignments to minimize conflicts
             Example: 'Agent 1: Fix all violations in adgn/agent/persist/*'
                      'Agent 2: Fix all violations in adgn/mcp/policy_gateway/*'

          5. Return:
             - Consolidated violation report
             - Recommended parallelization strategy with rationale
             - Specific agent task assignments
             - Dependency graph if some fixes must be sequential"
```

##### Wave FINAL.3 (28 parallel agents - Fix Violations)
**Depends on**: Wave FINAL.2 complete
```
Agent F.FIX.1: Fix walrus-get-pattern violations
  Dependencies: Consolidated report
  Prompt: "Fix all walrus-get-pattern violations in adgn/ code.
          Use consolidated report for context.
          Make minimal, focused changes.
          Run tests after each file change.
          Commit with descriptive message."

Agent F.FIX.2: Fix useless-test-classes violations
  Dependencies: Consolidated report
  Prompt: "Fix all useless-test-classes violations.
          Run tests to ensure no breakage.
          Commit changes."

[... agents F.FIX.3 through F.FIX.28 for each scan type ...]

Agent F.FIX.28: Fix fastmcp-documentation-patterns violations
  Dependencies: Consolidated report
  Prompt: "Fix all fastmcp-documentation-patterns violations.
          Run tests. Commit changes."
```

##### Wave FINAL.4 (Verification - 3 parallel agents)
**Depends on**: Wave FINAL.3 complete
```
Agent F.V1: Re-run All Scans
  Prompt: "Re-run all 28 code quality scans.
          Verify zero violations remain.
          Report any remaining issues."

Agent F.V2: Run Full Test Suite
  Prompt: "Run complete test suite after all fixes.
          Ensure no regressions.
          Check code coverage maintained ≥80%."

Agent F.V3: Type Check & Quality Gates
  Prompt: "Run mypy on entire adgn/ codebase.
          Run ruff check.
          Verify all quality gates pass.
          Return comprehensive quality report."
```

##### Wave FINAL.5 (Final Commit - 1 agent)
**Depends on**: Wave FINAL.4 complete
```
Agent F.FINAL: Create Quality Enforcement Commit
  Prompt: "Create final commit consolidating all quality fixes.
          Commit message should summarize:
          - Number of violations fixed by category
          - Files affected
          - Test results
          - Quality metrics improvement
          Push to remote branch."
```

---

### Summary: Critical Path & Parallelism

#### Critical Path (Sequential Dependencies)
```
Phase 0 → Phase 1 → Phase 3 → Phase 4 → Phase 5 → Phase FINAL
            ↓
       Phase 2 (overlaps after 1.2) ────────────┘
```

#### Maximum Parallelism by Wave

| Wave | Parallel Agents | Duration Est. | Dependencies |
|------|----------------|---------------|--------------|
| 0.1 | 2 | 1 hour | None |
| 0.2 | 3 | 1 hour | 0.1 |
| 0.3 | 4 | 1 hour | 0.2 |
| 0.4 | 2 | 0.5 hour | 0.3 |
| 0.5 | 5 | 0.5 hour | 0.4 |
| **1.1** | **4** | **0.5 day** | **Phase 0** |
| 1.2 | 3 | 1 day | 1.1 |
| **2.1** | **3** | **0.5 day** | **1.2.A** (starts early!) |
| 1.3 | 2 | 0.5 day | 1.2 |
| 2.2 | 3 | 0.5 day | 2.1, 1.2.B |
| 1.4 | 3 | 0.5 day | 1.3 |
| 2.3 | 4 | 1 day | 2.2 |
| 2.4 | 2 | 0.5 day | 2.3 |
| **3.1** | **2** | **0.5 day** | **1.2** |
| 3.2 | 2 | 0.25 day | 3.1 |
| 3.3 | 1 | 0.25 day | 3.2 |
| **4.1** | **4** | **1 day** | **1-3** |
| 4.2 | 3 | 1 day | 4.1 |
| 4.3 | 2 | 0.5 day | 4.2 |
| 5.1 | 3 | 0.5 day | Phase 4 |
| 5.2 | 1 | 0.25 day | 5.1 |
| **FINAL.1** | **28** | **2 hours** | **Phase 5** (scan all code) |
| FINAL.2 | 1 | 0.5 hour | FINAL.1 (consolidate) |
| **FINAL.3** | **28** | **2-3 hours** | **FINAL.2** (fix violations) |
| FINAL.4 | 3 | 1 hour | FINAL.3 (verify) |
| FINAL.5 | 1 | 0.25 hour | FINAL.4 (commit) |

#### Timeline Comparison

**Sequential**: 20-23 days
**Parallel**: 8-10 days

**Speedup**: ~2.5x

#### Resource Requirements

**Peak concurrency**: 28 agents (Wave FINAL.1, FINAL.3 - code quality scans)
**Average concurrency**: 2-4 agents
**Total agents**: 147 agents across all waves (28 waves total)

### Execution Strategy

1. **Phase 0**: Full autonomous execution (4-6 hours)
   - Type consolidation, persistence models, DB schema, middleware fixes
   - 5 waves, 16 agents

2. **Phase 1**: Backend MCP server implementation (3-4 days)
   - Infrastructure, resources, tools, notifications
   - 4 waves, 15 agents
   - Can pause after Wave 1.2 for checkpoint

3. **Phase 2**: Frontend UI implementation (2-3 days)
   - Starts early (overlaps with Phase 1 after Wave 1.2)
   - MCP client, UI components, real-time updates
   - 4 waves, 14 agents

4. **Phase 3**: Shared type generation (1 day)
   - Python → TypeScript type generation
   - 3 waves, 5 agents

5. **Phase 4**: Comprehensive testing (2-3 days)
   - Unit, integration, E2E, performance, security tests
   - 3 waves, 9 agents

6. **Phase 5**: Cleanup and documentation (1 day)
   - Remove WebSocket code, finalize docs
   - 2 waves, 4 agents

7. **Phase FINAL**: Code quality enforcement (4-6 hours)
   - Run all 28 code quality scans in parallel
   - Consolidate violations, fix in parallel
   - Re-verify, final commit
   - 5 waves, 60 agents (28 scan, 1 consolidate, 28 fix, 3 verify, 1 commit)

### Wave 1.1.C Fixes (Completed 2025-11-19)

**Status**: ✅ COMPLETED

Fixed critical misspecifications in wave 1.1 implementation before proceeding with full parallel execution plan.

#### Issues Fixed

1. **Schema: `approval_policies.version` → `approval_policies.id`**
   - **Problem**: Field named `version` implied per-agent versioning, but it's actually a globally unique identifier
   - **Solution**: Renamed to `id` to clarify that it's globally unique across all agents
   - **Files changed**:
     - `adgn/src/adgn/agent/persist/sqlite.py` (schema + queries)
     - `adgn/src/adgn/mcp/approval_policy/server.py` (reload logic)

2. **Schema: `policy_proposals` PK from `(agent_id, id)` → `id`**
   - **Problem**: Composite PK suggested agent-scoped IDs, but proposal IDs are globally unique UUIDs
   - **Solution**: Changed to single-column PK `id`
   - **Files changed**:
     - `adgn/src/adgn/agent/persist/sqlite.py` (schema definition)
   - **Note**: All existing queries remain compatible (defensive WHERE clauses still check both)

3. **Bug: Middleware type handling**
   - **Problem**: Middleware was passing dict to ToolCallExecution.output which expects mcp.types.CallToolResult
   - **Solution**: Use to_pydantic() to convert FastMCP results directly to MCP types
   - **Files changed**:
     - `adgn/src/adgn/mcp/policy_gateway/middleware.py`
     - `adgn/tests/mcp/policy_gateway/test_middleware_lifecycle.py` (removed skip decorator)

4. **Bug: Field casing in `as_minimal_json`**
   - **Problem**: Function was using snake_case field names but MCP types use camelCase
   - **Solution**: Updated to use MCP field names (isError, structuredContent) directly
   - **Files changed**:
     - `adgn/src/adgn/mcp/_shared/calltool.py`

5. **Documentation: TODO for table merging**
   - **Added**: Future enhancement suggestion to merge `policy_proposals` and `approval_policies` tables
   - **Rationale**: Similar structure (id, agent_id, content, timestamps, status/metadata), proposals "graduate" to policies
   - **Location**: `plan.md` "Future Enhancements" section

#### Impact on Parallel Execution Plan

- No blocking impact - these were schema/naming fixes
- Wave 1.1.D (Approval Engine Integration) can proceed without modifications
- All subsequent waves can proceed as planned

### Additional Type Safety Improvements (2025-11-19)

**Status**: ✅ COMPLETED

Further improvements to type safety and code consistency after Wave 1.1.C.

#### Improvements Made

1. **Made RunRow.agent_id non-nullable**
   - **Rationale**: Every run must be associated with an agent
   - **Changes**:
     - `RunRow.agent_id: AgentID | None` → `RunRow.agent_id: AgentID`
     - `start_run(agent_id: AgentID | None, ...)` → `start_run(agent_id: AgentID, ...)`
     - Updated SQLite implementation to match

2. **Baked row_factory into connection methods**
   - **Problem**: Many methods redundantly set `db.row_factory = aiosqlite.Row` after getting connection
   - **Solution**: Set row_factory in both `_open()` and `_db_connection()` helper methods
   - **Impact**: Cleaner code, guaranteed consistent row behavior across all methods

3. **Function renaming for clarity**
   - `to_pydantic()` → `convert_fastmcp_result()` (better describes purpose of converting FastMCP to MCP types)
   - `as_minimal_json()` → `serialize_tool_result_compact()` (clearer name for JSON serialization)
   - Updated all 14 files with imports and usages

4. **Parameter naming consistency**
   - `load_policy(version=...)` → `load_policy(policy_id=...)` to align with schema where `approval_policies.version` was renamed to `approval_policies.id`

5. **Made ApprovalRecord.agent_id non-nullable**
   - **Rationale**: Every approval must be associated with an agent
   - **Changes**:
     - `ApprovalRecord.agent_id: AgentID | None` → `ApprovalRecord.agent_id: AgentID`
     - `record_approval(agent_id: AgentID | None, ...)` → `record_approval(agent_id: AgentID, ...)`
     - Updated `list_approvals()` to remove conditional wrapping

6. **AgentID newtype implementation**
   - Created `adgn/src/adgn/agent/types.py` with `AgentID = NewType("AgentID", str)`
   - Updated ~40+ function signatures across persistence Protocol and implementation
   - Avoided circular imports by creating dedicated types module

## Timeline Estimate

- **Phase 0** (Type Consolidation & Data Models): 1-2 days
- **Phase 1** (Backend): 3-4 days
- **Phase 2** (Frontend): 2-3 days
- **Phase 3** (Shared Models): 1 day
- **Phase 4** (Testing): 2-3 days
- **Phase 5** (Cleanup): 1 day
- **Total**: ~2.5 weeks

## Data Model Improvements & Bug Fixes

### Type Consolidation

**ApprovalToolCall vs ToolCall:**

Two similar types exist:
- `ApprovalToolCall` in `adgn/src/adgn/agent/approvals.py`: `{name, call_id, args_json}`
- `ToolCall` in `adgn/src/adgn/agent/server/protocol.py`: `{type, name, call_id, args_json}`

**Decision**: Consolidate to use `ToolCall` from `protocol.py` or rename `ApprovalToolCall` to `ToolCall` in `approvals.py`. The `protocol.py` version has an extra `type` discriminator field for union types. For the approval/persistence use case, we likely don't need the discriminator.

**Recommendation**: Keep `ApprovalToolCall` in `approvals.py` but rename it to `ToolCall` since it's the simpler version without the discriminator. Update all references accordingly. If `protocol.py` needs the discriminated version, it can keep its own `ToolCall` with the discriminator.

**TODO**:
- [ ] Rename `ApprovalToolCall` → `ToolCall` in `approvals.py`
- [ ] Update all imports and references (middleware, persistence, plan)
- [ ] Verify no conflicts with `protocol.py` version

### ApprovalRecord Enhancement

**Current Issues:**
1. **Naming**: `ApprovalRecord` tracks all tool calls (not just approvals) - should be `ToolCallRecord`
2. **Untyped details**: Uses generic `dict[str, JsonValue]` instead of typed fields
3. **Missing data**: Tool args, outputs, and execution timing not captured
4. **Middleware bug**: USER approvals/rejections recorded with POLICY outcome codes

**Required Changes:**

```python
class Decision(BaseModel):
    """Decision made about a tool call.

    All fields are REQUIRED. The entire Decision object is optional on ToolCallRecord.
    """
    outcome: ApprovalOutcome  # POLICY_ALLOW, USER_APPROVE, etc. (required)
    decided_at: datetime  # Also serves as execution start time (required)
    reason: str | None  # For denials/rejections (required, but value can be None)

class ToolCallExecution(BaseModel):
    """Tool execution result.

    All fields are REQUIRED. The entire ToolCallExecution object is optional on ToolCallRecord.
    """
    completed_at: datetime  # Required
    output: mcp_types.CallToolResult  # Required

# TODO: Rename ApprovalRecord → ToolCallRecord
class ToolCallRecord(BaseModel):
    """Complete tool call record from policy gate (tracks ALL calls through gate)."""
    call_id: str
    run_id: str | None
    agent_id: str | None

    # Tool call info (reuse ToolCall type - formerly ApprovalToolCall)
    tool_call: ToolCall  # {name, call_id, args_json}

    # Decision info (None if not yet decided)
    # decision.decided_at also serves as execution start time
    decision: Decision | None

    # Execution result (None if not completed)
    # State detection: decision!=None && execution==None → EXECUTING
    execution: ToolCallExecution | None
```

**TODOs:**
- [ ] **Type consolidation**: Rename `ApprovalToolCall` → `ToolCall` in `approvals.py` and update all references
- [ ] Fix middleware bug: Lines 242, 254 in `adgn/src/adgn/mcp/policy_gateway/middleware.py`
  - USER approvals currently recorded as `POLICY_ALLOW` (should be `USER_APPROVE`)
  - USER rejections currently recorded as `POLICY_DENY_ABORT` (should be `USER_DENY_ABORT`)
- [ ] Pass tool arguments to `record_approval()` calls in middleware
- [ ] Track execution start/completion in middleware (before/after `call_next()`)
- [ ] Add typed fields to ApprovalRecord (or create ToolCallRecord)
- [ ] Update database schema to support new fields
- [ ] Update `list_approvals()` to return enriched records
- [ ] Consider renaming to `ToolCallRecord` for clarity

### Agent State Tracking

**Agent States (for sidebar UI):**

| State | Color | Meaning | Detection |
|-------|-------|---------|-----------|
| **WAITING_APPROVAL** | 🔴 Red | Has pending approvals | `len(approval_hub.pending) > 0` |
| **EXECUTING** | 🟡 Yellow | Tool call in flight | `decision != None && execution == None` |
| **SAMPLING** | 🔵 Blue | Agent loop active (local only) | `local_runtime.agent.is_running()` |
| **IDLE** | 🟢 Green | No pending work | Default state |

**State Priority** (if multiple apply): WAITING_APPROVAL > EXECUTING > SAMPLING > IDLE

**MCP Resource:**
```typescript
resource://agents/{id}/state
  → {
      agent_id: string,
      state: "waiting_approval" | "executing" | "sampling" | "idle"
    }
```

## Future Enhancements (Beyond Phase 5)

These features would improve production deployment:

- [ ] **Idle Cleanup**: Auto-shutdown infrastructure after N minutes of inactivity per agent_id
- [ ] **Token Reload**: Hot-reload token mapping file without restart (watch file for changes)
- [ ] **Unified Instructions**: Merge server instructions in initialization message
- [ ] **Metrics**: Per-agent usage metrics (tool calls, approvals, policy evaluations)
- [ ] **MCP Elicitations**: Replace tool-based approvals with standardized elicitation workflow (Phase 6+)
- [ ] **SQLAlchemy Migration**: Migrate from raw aiosqlite to SQLAlchemy ORM for better type safety and migrations
- [ ] **Remove SidecarBundle**: Eliminate SidecarBundle abstraction - currently a no-op for external agents, adds unnecessary complexity
- [ ] **Detailed Agent State**: Instead of state priority logic (WAITING_APPROVAL > EXECUTING > SAMPLING > IDLE), track detailed state including lists of pending approvals, executing tools, etc. This would provide richer UI information without needing priority resolution.
- [ ] **Merge Policy Tables**: Consider merging `policy_proposals` and `approval_policies` tables - they have very similar structure (id, agent_id, content, timestamps, status/metadata), and policy_proposals essentially "graduate" to approval_policies when approved. Could simplify schema and reduce duplication.
- [ ] **Unfold ApprovalRecord.details**: Replace generic `details: dict[str, JsonValue] | None` with typed nested models (`tool_call: ToolCall`, `execution: ToolCallExecution | None`). This would enable tracking EXECUTING state (decision!=None && execution==None), displaying full tool call timeline with args and outputs, and proper type safety instead of generic dict. Note: ApprovalRecord is deprecated/legacy - migrate to ToolCallRecord which already has this structure.

## References

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-06-18/)
- [MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Elicitations](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation)
- [Streamable HTTP Transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
