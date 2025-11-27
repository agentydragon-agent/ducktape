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

### Overview

Single `/mcp` endpoint serves both users and agents. Bearer token determines routing:

```
                          ┌─────────────────────────────────────────────┐
                          │              /mcp endpoint                   │
                          │     (same port, same URL for both)          │
                          └─────────────────┬───────────────────────────┘
                                            │
                          ┌─────────────────┴───────────────────────────┐
                          │         Bearer Token Router                  │
                          │   (FastMCP TokenVerifier middleware)        │
                          └─────────┬───────────────────────┬───────────┘
                                    │                       │
                    ┌───────────────┴───────┐   ┌───────────┴───────────────┐
                    │   User Token          │   │   Agent Token             │
                    │   → User Compositor   │   │   → Agent Compositor      │
                    └───────────────────────┘   └───────────────────────────┘
```

### Architecture: User-Facing Compositor (2-level)

```
User-Facing Global Compositor
├── agents (management server)
│   ├── list_agents
│   ├── create_agent
│   ├── delete_agent
│   └── boot_agent ──► lazy mounts per-agent compositor
│
└── agent_{id} (per-agent user compositor, mounted on boot_agent)
    ├── reader (policy.py)
    ├── admin (approve/reject/set)
    ├── agent_control (send_prompt, abort_run)
    └── snapshot resource
```

### Architecture: Agent-Facing Compositor

```
Agent Compositor (per-agent, gated)
├── reader (policy.py)
├── policy_proposer
├── ui
├── chat.human / chat.assistant
├── loop
├── runtime (exec)
└── [Policy Gateway Middleware] ─► gates all tool calls
```

### Design Decisions

1. **Single endpoint, token-based routing**
   - Same `/mcp` URL for users and agents
   - Bearer token determines which compositor handles request
   - Use FastMCP's `TokenVerifier` interface for auth

2. **Lazy mounting via `boot_agent(id)`**
   - Global compositor mounts `agents` server at startup
   - `boot_agent(id)` ensures agent is live, then mounts its user compositor
   - Uses `asyncio.Lock` for concurrent calls - boot once, others succeed

3. **AgentID type**
   - Use existing `AgentID = NewType("AgentID", str)` from `agent/types.py`
   - Already has narrow charset (semantic str wrapper)
   - Safe to use as tool prefix: `agent_{id}_send_prompt`

4. **Unmount on shutdown**
   - When agent shuts down, unmount its user compositor from global
   - Uses Compositor's `unmount_server()` method

5. **Shared PolicyEngine**
   - Single engine per agent, shared between both compositors
   - Both mount same `.reader`, `.policy_proposer`, `.admin` servers

### Implementation Steps

#### Step 1: Create `mcp_bridge` Module

```
adgn/src/adgn/agent/mcp_bridge/
├── __init__.py
├── auth.py                  # TokenVerifier impl, token→compositor routing
├── compositor_factory.py    # create_global_compositor()
├── server.py               # InfrastructureRegistry class
└── servers/
    └── agents.py           # Agent management MCP server
```

#### Step 2: InfrastructureRegistry

```python
@dataclass
class InfrastructureRegistry:
    persistence: Persistence
    docker_client: DockerClient
    mcp_config: MCPConfig
    initial_policy: str | None
    global_compositor: Compositor  # Reference for mounting

    _agents: dict[AgentID, AgentContainer] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def boot_agent(self, agent_id: AgentID) -> None:
        """Ensure agent is live and mount its user compositor."""
        async with self._lock:
            if agent_id in self._agents:
                return  # Already booted
            container = await self._create_container(agent_id)
            self._agents[agent_id] = container
            # Mount user compositor to global
            await self.global_compositor.mount_inproc(
                f"agent_{agent_id}",
                container.user_compositor
            )

    async def shutdown_agent(self, agent_id: AgentID) -> None:
        """Shutdown agent and unmount its user compositor."""
        async with self._lock:
            if agent_id not in self._agents:
                return
            # Unmount from global
            await self.global_compositor.unmount_server(f"agent_{agent_id}")
            container = self._agents.pop(agent_id)
            await container.shutdown()
```

#### Step 3: Bearer Token Auth

FastMCP provides `TokenVerifier` interface. Implement custom verifier:

```python
class AgentTokenVerifier:
    """Routes requests based on bearer token type."""

    def __init__(
        self,
        user_tokens: dict[str, str],   # token → user_id
        agent_tokens: dict[str, AgentID],  # token → agent_id
    ):
        self.user_tokens = user_tokens
        self.agent_tokens = agent_tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        if token in self.user_tokens:
            return AccessToken(
                token=token,
                client_id=self.user_tokens[token],
                scopes=["user"],
                expires_at=None,
            )
        if token in self.agent_tokens:
            return AccessToken(
                token=token,
                client_id=str(self.agent_tokens[token]),
                scopes=["agent"],
                expires_at=None,
            )
        return None
```

#### Step 4: Dual Compositor per Agent

Modify `AgentContainer`:

```python
class AgentContainer:
    _agent_compositor: Compositor  # For LLM (has gateway)
    _user_compositor: Compositor   # For UI (no gateway)

    @property
    def user_compositor(self) -> Compositor:
        return self._user_compositor

    async def _setup_compositors(self):
        engine = self._policy_engine

        # Agent compositor (existing, add gateway)
        self._agent_compositor.add_middleware(engine.gateway)
        await self._agent_compositor.mount_inproc("reader", engine.reader)
        await self._agent_compositor.mount_inproc("policy_proposer", engine.policy_proposer)
        # ... other servers

        # User compositor (new, no gateway)
        self._user_compositor = Compositor(f"user-{self.agent_id}")
        await self._user_compositor.mount_inproc("reader", engine.reader)
        await self._user_compositor.mount_inproc("admin", engine.admin)
        await self._user_compositor.mount_inproc("agent_control", self._agent_control_server)
```

#### Step 5: Agent Control Server

```python
def make_agent_control_server(container: AgentContainer) -> FastMCP:
    mcp = FastMCP("agent_control")

    @mcp.tool()
    async def send_prompt(text: str) -> str:
        await container.send_prompt(text)
        return "Prompt sent"

    @mcp.tool()
    async def abort_run() -> str:
        await container.abort()
        return "Run aborted"

    return mcp
```

#### Step 6: Fix app.py

```python
from adgn.agent.mcp_bridge.compositor_factory import create_global_compositor
from adgn.agent.mcp_bridge.server import InfrastructureRegistry
from adgn.agent.mcp_bridge.auth import AgentTokenVerifier

# In lifespan:
registry = InfrastructureRegistry(...)
global_comp = await create_global_compositor(registry)

# Route based on token
verifier = AgentTokenVerifier(user_tokens, agent_tokens)
# Use FastMCP's auth middleware with custom verifier
```

### Implementation Flow

```
1. User connects with user bearer token
   → Routes to user-facing global compositor
   → Calls: agents_boot_agent(id="abc123")

2. InfrastructureRegistry.boot_agent("abc123")
   - Acquires lock
   - Creates AgentContainer (both compositors)
   - Mounts user_compositor as "agent_abc123"
   - Releases lock

3. User can now call:
   - agent_abc123_send_prompt(text="Hello")
   - agent_abc123_abort_run()
   - agent_abc123_admin_approve_call(call_id="...")

4. Agent connects with agent bearer token
   → Routes directly to agent's agent_compositor
   → Tool calls gated by policy gateway middleware
```

### Notes

- **No existing bearer token code on devel** - needs full implementation
- **FastMCP auth**: Use `TokenVerifier` interface, `InMemoryOAuthProvider` as reference
- **Props specimens** reference planned `mcp_bridge/auth.py` that was never created

### Dependencies

- PolicyEngine with `.reader`, `.policy_proposer`, `.admin` servers (✅ Done)
- Compositor with middleware support (✅ Done)
- HTTP/SSE MCP transport on `/mcp` (exists but broken due to missing imports)
- FastMCP TokenVerifier auth (available in fastmcp.server.auth)
