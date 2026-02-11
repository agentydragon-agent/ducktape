# MCP Server Architecture: Single-Agent vs Cross-Agent

## Overview

The system has **two distinct layers** of MCP servers:

1. **Single-Agent Scope**: Each agent runtime has its own set of MCP servers mounted in its compositor
2. **Cross-Agent Scope**: The `agents` MCP bridge server provides unified management across ALL agents

This document explains why certain functionality appears "duplicated" between these layers, and why this is intentional architectural separation.

## Single-Agent MCP Servers (Per-Agent)

Each agent runtime mounts these servers in its compositor (`adgn/src/adgn/mcp/`):

### 1. `approval_policy` Server

**Location**: `adgn/src/adgn/mcp/approval_policy/server.py`

**Three Variants** (mounted separately):
- **Reader** (`approval_policy`): Resources only (policy text, proposals)
- **Proposer** (`approval_policy_proposer`): Tools for creating/withdrawing proposals
- **Admin** (`approval_policy_admin`): Tools for approving/rejecting proposals, setting policy

**Resources**:
- `resource://approval-policy/policy.py` - Active policy source code
- `resource://approval-policy/proposals/list` - All proposals with status
- `resource://approval-policy/proposals/{id}` - Individual proposal details
- `resource://policies/list` - Policy library index
- `resource://policies/{id}` - Policy library item details

**Proposer Tools**: `create_proposal`, `withdraw_proposal`

**Admin Tools**: `approve_proposal`, `reject_proposal`, `set_policy_text`, `validate_policy`, `reload_policy`, `create_policy`, `update_policy`, `delete_policy`

**Decision Tool**: `decide` - Evaluates policy for a tool call via Docker-backed evaluator

### 2. `chat` Server

**Location**: `adgn/src/adgn/mcp/chat/server.py`

**Two Servers per Agent**:
- `chat.human` (for user messages)
- `chat.assistant` (for agent messages)

**Resources**:
- `chat://head` - Latest message ID sentinel
- `chat://last-read` - Read high-water mark
- `chat://messages/{id}` - Individual message

**Tools**: `post`, `read_pending_messages`

### 3. `loop` Server

**Location**: `adgn/src/adgn/mcp/loop/server.py`

**Tool**: `yield_turn` - Signal to orchestrator to end agent's turn

### 4. `compositor` Server

**Location**: `adgn/src/adgn/mcp/compositor/server.py`

**Purpose**: Aggregates child MCP servers for a single agent

**Python API**:
- `mount_server(name, spec)` - Mount external MCP server
- `mount_inproc(name, app)` - Mount local FastMCP server
- `unmount_server(name)` - Remove mounted server
- `reconfigure(cfg)` - Update all mounts from config
- `sampling_snapshot()` - Full state snapshot of all mounted servers
- `get_child_client(name)` - Get persistent client to mounted server

### 5. `compositor_meta` Server

**Location**: `adgn/src/adgn/mcp/compositor_meta/server.py`

**Resource**: `compositor://state/{server}` - Per-mount status (initializing/running/failed)

## Cross-Agent MCP Server (Global)

### `agents` Server

**Location**: `adgn/src/adgn/agent/mcp_bridge/servers/agents.py`

**Purpose**: Unified management interface across ALL agents

**Already Implemented Resources**:
- `resource://agents/list` - All agents with capabilities
- `resource://agents/{id}/state` - Compositor sampling state for agent
- `resource://agents/{id}/approvals/pending` - Pending approvals for agent
- `resource://approvals/pending` - **Global** pending approvals across all agents
- `resource://agents/{id}/approvals/history` - Historical approval decisions
- `resource://agents/{id}/policy/proposals` - Policy proposals for agent

**Already Implemented Tools**:
- `approve_tool_call(agent_id, call_id)` - Approve pending tool call
- `reject_tool_call(agent_id, call_id, reason)` - Reject pending tool call
- `abort_agent(agent_id)` - Abort running agent loop

**Planned Tools** (Wave B):
- `create_agent`, `delete_agent`, `boot_agent` - Agent lifecycle
- `update_mcp_config`, `attach_server`, `detach_server` - Compositor management
- `prompt` - Send user message to agent (via chat.human)
- `deny_tool_call`, `deny_abort` - Alternative naming for rejections
- `set_policy`, `approve_proposal`, `reject_proposal` - Policy management

**Planned Resources** (Wave B):
- `resource://agents/{id}/info` - Rich agent metadata
- `resource://agents/{id}/snapshot` - Compositor snapshot

## Why This Appears "Duplicated"

| Cross-Agent Tool | Single-Agent Equivalent | Relationship |
|------------------|-------------------------|--------------|
| `approve_proposal` | `approval_policy_admin.approve_proposal` | **Routing wrapper** - adds agent_id parameter |
| `reject_proposal` | `approval_policy_admin.reject_proposal` | **Routing wrapper** - adds agent_id parameter |
| `set_policy` | `approval_policy_admin.set_policy_text` | **Routing wrapper** - different name, same function |
| `prompt` | `chat.human.post` | **Routing wrapper** - semantic wrapper for sending message |
| `attach_server` | `compositor.mount_server()` | **MCP tool wrapper** - exposes Python API as MCP tool |
| `detach_server` | `compositor.unmount_server()` | **MCP tool wrapper** - exposes Python API as MCP tool |
| `update_mcp_config` | `compositor.reconfigure()` | **MCP tool wrapper** - exposes Python API as MCP tool |
| `agents/{id}/snapshot` | `compositor.sampling_snapshot()` | **Routing wrapper** - exposes per-agent data cross-agent |

## Architectural Principles

### 1. Single-Agent Servers: Fine-Grained Control

Each agent's compositor mounts its own set of MCP servers. These provide:
- **Isolated state**: Each agent has its own approval policy, chat history, etc.
- **Direct access**: The agent can call its own servers without routing
- **Modular capabilities**: Servers can be mounted/unmounted dynamically

### 2. Cross-Agent Server: Unified Facade

The `agents` server acts as a **facade/aggregator** that:
- **Routes operations**: Takes `agent_id` parameter and routes to appropriate agent's infrastructure
- **Provides cross-agent views**: Global pending approvals, agent list, etc.
- **Adds orchestration**: Agent creation/deletion, cross-agent coordination

### 3. Thin Routing Layer (NO Business Logic Duplication)

Cross-agent tools must be **thin wrappers** that:
1. Accept `agent_id` parameter
2. Look up agent's infrastructure via `registry.get_infrastructure(agent_id)`
3. Delegate to existing single-agent MCP servers or Python APIs
4. Handle routing errors (agent not found, not authorized, etc.)

**Example Pattern**:
```python
@server.tool()
async def approve_proposal(agent_id: str, proposal_id: str) -> None:
    """Approve a policy proposal for an agent."""
    infra = await registry.get_infrastructure(AgentID(agent_id))

    # Delegate to per-agent approval_policy_admin server
    client = infra.compositor.get_child_client("approval_policy_admin")
    await client.call_tool("approve_proposal", {"id": proposal_id})
```

## Implementation Guidelines

### DO ✅

- Route to existing single-agent servers via `compositor.get_child_client()`
- Delegate to Python APIs (e.g., `compositor.mount_server()`)
- Add agent_id parameter to tools
- Provide error handling for agent not found
- Aggregate cross-agent data (e.g., global pending approvals)

### DON'T ❌

- Reimplement policy evaluation logic
- Duplicate approval decision logic
- Copy compositor management logic
- Create parallel state management
- Bypass single-agent servers

## Benefits of This Architecture

1. **Single Source of Truth**: Business logic lives in one place (single-agent servers)
2. **Flexibility**: Each agent can have different mounted servers, policies, configurations
3. **Isolation**: Agent failures don't affect other agents
4. **Composability**: Cross-agent tools can be delegated to other agents for self-orchestration
5. **Testing**: Single-agent servers can be tested in isolation
6. **Maintainability**: Changes to business logic only need to happen in one place

## Future Considerations

If >20 routing tools emerge, consider creating a decorator pattern:

```python
@route_to_agent_server("approval_policy_admin", "approve_proposal")
async def approve_proposal(agent_id: str, proposal_id: str) -> None:
    pass  # Decorator handles routing
```

However, for Wave B, **manual routing is preferred** because:
- Only ~10 routing tools planned
- Explicit code is clearer for maintenance
- Custom error handling per tool is easier
- FastMCP tool registration may not support decorator wrapping

## Security Integration: Approval Policy + Seatbelt

The MCP security model uses **two complementary layers** for defense-in-depth:

### 1. Approval Policy (MCP Layer - Semantic Gating)

**Location**: `adgn/src/adgn/mcp/approval_policy/`

Controls which MCP tools can be invoked by name and arguments via custom Python policies. Decisions include:
- `allow`: Tool call proceeds
- `deny_continue`: Block, agent continues
- `deny_abort`: Block, agent's turn aborts
- `ask`: Defer to human via UI

See `adgn/src/adgn/mcp/policy_gateway/middleware.py` for the middleware that intercepts all tool calls.

### 2. Seatbelt (Process Layer - OS Isolation)

**Location**: `adgn/src/adgn/seatbelt/`

Provides macOS kernel-level sandboxing for specific operations (e.g., `seatbelt_exec` tool). Even if approval policy mistakenly allows a dangerous operation, seatbelt enforces OS-level resource restrictions via SBPL policies.

**Security boundary**:
- Approval policy gates at the MCP tool level (semantic control)
- Seatbelt enforces at the OS syscall level (enforcement)

For detailed architecture and integration points, see **`seatbelt/MCP_SECURITY_INTEGRATION.md`**.

## Related Documentation

- `EXECUTION_PLAN.md` - Wave B implementation plan for cross-agent tools
- `plan.md` - Overall project plan and HTTP to MCP migration
- `adgn/src/adgn/mcp/approval_policy/server.py` - Policy server implementation
- `adgn/src/adgn/mcp/compositor/server.py` - Compositor implementation
- `adgn/src/adgn/agent/mcp_bridge/servers/agents.py` - Cross-agent server implementation
- `seatbelt/MCP_SECURITY_INTEGRATION.md` - Defense-in-depth security model for seatbelt + approval policy
- `seatbelt/TODO.md` - Seatbelt roadmap with MCP integration items
