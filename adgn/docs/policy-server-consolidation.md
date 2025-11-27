# Policy Server Consolidation Plan

## Goal

Consolidate policy and approval handling into a single `PolicyEngine` class that owns all policy-related servers, state, and middleware.

## Status

| Phase | Status |
|-------|--------|
| Phase 1-3: Core consolidation | ✅ Done |
| Phase 4: Cleanup deprecated code | ✅ Done |
| Phase 5: Two-compositor architecture | ⏳ Next |

## Completed

### Phase 1-3: Core Consolidation

- `_ApprovalHub` and `_PolicyGatewayMiddleware` moved into `engine.py` as private classes
- `pending://calls` resource added to reader (hub changes trigger broadcast)
- `decide_call` and `decide_proposal` tools on admin server
- Deleted `mcp/approvals/` and `mcp/policy_gateway/` directories
- `container.py` simplified: uses `engine.gateway`
- `runtime.py` no longer accesses PolicyEngine internal state
- Test fixtures migrated: `pg_client`, `make_pg_client`, `make_pg_compositor`, `make_decision_engine`

### Phase 4: Cleanup Deprecated Code

- Removed `ApprovalPolicyEngine` class and related fixtures from tests
- Removed `ApprovalHub` class (now `_ApprovalHub` private in engine.py)
- Removed deprecated `make_policy_engine` factory function
- Updated `approvals.py` to only export: `ApprovalRequest`, `ApprovalToolCall`, `WellKnownTools`, `load_default_policy_source`
- Simplified constants: removed `APPROVAL_POLICY_SERVER_NAME_READER/_PROPOSER/_APPROVER`
- Added new constants: `POLICY_PROPOSER_SERVER_NAME`, `POLICY_ADMIN_SERVER_NAME`
- Added `docker_client` fixture to `tests/conftest.py`
- Renamed `stub_approval_policy_engine` fixture to `stub_policy_engine`

## Phase 5: Two-Compositor Architecture

### Background

The current architecture has a single compositor per agent that serves both the agent (LLM) and the user (UI). Phase 5 separates these concerns:

- **Agent compositor**: Has policy gateway middleware that gates all tool calls
- **User compositor**: Exposes admin tools without policy gating (trusted user)

### Problem: Broken `app.py` Imports

`app.py` currently imports from non-existent modules:
```python
from adgn.agent.mcp_bridge.compositor_factory import create_global_compositor
from adgn.agent.mcp_bridge.server import InfrastructureRegistry
```

These were planned but never implemented. Phase 5 must either:
1. Create these modules, or
2. Refactor app.py to use a different approach

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Global Level                                   │
│  /mcp endpoint → Global Compositor → Per-Agent User Compositors         │
└─────────────────────────────────────────────────────────────────────────┘

Per-Agent Structure:
┌──────────────────────────────────────────────────────────────────────────┐
│ AgentContainer owns:                                                      │
│                                                                          │
│  ┌─────────────────────────────┐    ┌─────────────────────────────────┐ │
│  │   Agent Compositor          │    │    User Compositor               │ │
│  │   (for LLM tool calls)      │    │    (for UI/admin)               │ │
│  │                             │    │                                  │ │
│  │  - reader (policy.py)       │    │  - reader (policy.py)           │ │
│  │  - policy_proposer          │    │  - admin (approve/reject/set)   │ │
│  │  - ui                       │    │  - agent_control (send_prompt)  │ │
│  │  - chat.human/assistant     │    │  - snapshot resource            │ │
│  │  - loop                     │    │                                  │ │
│  │  - runtime (exec)           │    │                                  │ │
│  │  + Policy Gateway MW ✓      │    │  (no gateway - trusted)         │ │
│  └─────────────────────────────┘    └─────────────────────────────────┘ │
│                                                                          │
│  PolicyEngine owns both: .reader, .policy_proposer, .admin              │
└──────────────────────────────────────────────────────────────────────────┘
```

### Implementation Steps

#### Step 1: Create `mcp_bridge` Module Structure

New directory: `adgn/src/adgn/agent/mcp_bridge/`

```
mcp_bridge/
├── __init__.py
├── compositor_factory.py    # create_global_compositor()
├── server.py               # InfrastructureRegistry class
└── servers/
    └── agents.py           # Agent management tools (create/delete/list)
```

#### Step 2: InfrastructureRegistry (server.py)

Manages per-agent lifecycle and exposes:
- `list_agents()` - List all agents with status
- `create_agent(preset)` - Create new agent
- `delete_agent(id)` - Delete agent
- `boot_agent(id)` - Ensure agent is running

```python
@dataclass
class InfrastructureRegistry:
    persistence: Persistence
    docker_client: DockerClient
    mcp_config: MCPConfig
    initial_policy: str | None

    _agents: dict[str, AgentContainer] = field(default_factory=dict)

    async def ensure_live(self, agent_id: str) -> AgentContainer: ...
    async def create_agent(self, preset: str) -> str: ...
    async def delete_agent(self, agent_id: str) -> None: ...
```

#### Step 3: Global Compositor (compositor_factory.py)

Creates the global `/mcp` compositor that:
1. Mounts `agents` server (create/delete/list tools)
2. Dynamically mounts per-agent user compositors on demand

```python
async def create_global_compositor(
    registry: InfrastructureRegistry,
    gateway_client: Client | None = None,
) -> Compositor:
    comp = Compositor("global")

    # Mount agents management server
    agents_server = make_agents_server(registry)
    await comp.mount_inproc("agents", agents_server)

    # TODO: Dynamic per-agent sub-compositor mounting
    return comp
```

#### Step 4: AgentContainer Dual Compositor

Modify `AgentContainer` to create two compositors:

```python
class AgentContainer:
    _agent_compositor: Compositor  # For LLM (has gateway)
    _user_compositor: Compositor   # For UI (no gateway)

    async def _attach_inproc_servers(self, ui_bus):
        # Agent compositor (existing, add gateway)
        self._agent_compositor.add_middleware(self._policy_engine.gateway)
        await self._agent_compositor.mount_inproc("reader", engine.reader)
        await self._agent_compositor.mount_inproc("policy_proposer", engine.policy_proposer)
        # ... other servers

        # User compositor (new, no gateway)
        self._user_compositor = Compositor(f"user-{self.agent_id}")
        await self._user_compositor.mount_inproc("reader", engine.reader)
        await self._user_compositor.mount_inproc("admin", engine.admin)
        await self._user_compositor.mount_inproc("agent_control", agent_control_server)
```

#### Step 5: Agent Control Server

New server exposing:
- `send_prompt(text)` - Send user prompt to agent
- `abort_run()` - Abort current agent run

Currently these are HTTP endpoints; migrate to MCP tools.

#### Step 6: Fix app.py

Update `app.py` to use the new modules:
```python
from adgn.agent.mcp_bridge.compositor_factory import create_global_compositor
from adgn.agent.mcp_bridge.server import InfrastructureRegistry
```

### Design Decisions (Resolved)

1. **Dynamic mounting**: Lazy mount on `boot_agent(id)` call
   - Global compositor mounts `agents` server with tools: `list_agents`, `create_agent`, `delete_agent`, `boot_agent`
   - `boot_agent(id)` ensures agent is live, then mounts its user compositor to the global compositor
   - Uses Compositor's existing `mount_inproc()` for hot-mounting

2. **Agent ID routing**: Tool prefix via FastMCP's `mount(prefix=...)`
   - FastMCP's `mount()` automatically prefixes: `{prefix}_{tool}`
   - Example: `agent_123_send_prompt`, `agent_123_abort_run`
   - Resources: `snapshot://agent_123/state`
   - No query params or nested paths needed

3. **Shared PolicyEngine**: Yes, single engine per agent
   - Both agent and user compositors mount the same engine's servers
   - Shared state: pending calls, policy version, hub futures

### Implementation Flow

```
1. User calls: agents_boot_agent(id="123")
   ↓
2. InfrastructureRegistry.ensure_live("123")
   - Creates AgentContainer if not exists
   - Starts agent_compositor (for LLM)
   - Creates user_compositor (for UI)
   ↓
3. Global compositor mounts user_compositor:
   global_comp.mount_inproc(f"agent_{id}", user_comp)
   ↓
4. Tools now available as:
   - agent_123_send_prompt
   - agent_123_abort_run
   - agent_123_approve_call (via admin)
   Resources:
   - snapshot://agent_123/state
```

### Dependencies

- PolicyEngine with `.reader`, `.policy_proposer`, `.admin` servers (✅ Done)
- Compositor with middleware support (✅ Done)
- HTTP/SSE MCP transport on `/mcp` (exists but broken)
