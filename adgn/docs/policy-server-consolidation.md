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

#### Step 3: Bearer Token Auth & Routing

FastMCP provides `TokenVerifier` interface. Implement custom verifier that also routes:

```python
class TokenRouter:
    """Verifies tokens and routes to appropriate compositor."""

    def __init__(
        self,
        registry: InfrastructureRegistry,
        user_tokens: dict[str, str],       # token → user_id
        agent_tokens: dict[str, AgentID],  # token → agent_id (which agent this token belongs to)
    ):
        self.registry = registry
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
            agent_id = self.agent_tokens[token]
            return AccessToken(
                token=token,
                client_id=str(agent_id),
                scopes=["agent"],
                expires_at=None,
            )
        return None

    def get_compositor_for_token(self, token: str) -> Compositor | None:
        """Route to correct compositor based on token type."""
        if token in self.user_tokens:
            # User token → global user-facing compositor
            return self.registry.global_compositor
        if token in self.agent_tokens:
            # Agent token → that agent's agent-facing compositor
            agent_id = self.agent_tokens[token]
            container = self.registry.get_agent(agent_id)
            if container:
                return container.agent_compositor  # The gated one
        return None
```

**Key insight**: Agent tokens are per-agent. When agent presents its token, we look up which agent it belongs to and route directly to that agent's compositor (with policy gateway).

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
USER FLOW:
1. User connects with user bearer token
   → TokenRouter.get_compositor_for_token() → global_compositor
   → User sees: agents server + any booted agent_{id} sub-compositors

2. User calls: agents_boot_agent(id="abc123")
   - InfrastructureRegistry.boot_agent() acquires lock
   - Creates AgentContainer (agent_compositor + user_compositor)
   - Generates agent token for "abc123"
   - Mounts user_compositor as "agent_abc123" on global
   - Returns agent token to user (for agent to use)

3. User can now call (via global compositor):
   - agent_abc123_send_prompt(text="Hello")
   - agent_abc123_abort_run()
   - agent_abc123_admin_approve_call(call_id="...")

AGENT FLOW:
4. Agent connects with its agent bearer token
   → TokenRouter.get_compositor_for_token() → that agent's agent_compositor
   → Agent sees: reader, policy_proposer, ui, chat, loop, runtime
   → All tool calls gated by policy gateway middleware

5. Agent calls tools (e.g., runtime_exec)
   → Policy gateway middleware intercepts
   → Evaluates policy in Docker container
   → Allow/deny/ask decision
```

### Notes

- **No existing bearer token code on devel** - needs full implementation
- **FastMCP auth**: Use `TokenVerifier` interface, `InMemoryOAuthProvider` as reference
- **Props specimens** reference planned `mcp_bridge/auth.py` that was never created

### Token Configuration

#### Token File Format

Tokens are stored in YAML format at `~/.config/adgn/tokens.yaml`:

```yaml
# User tokens (admin access to global compositor)
users:
  admin: "user_token_abc123..."

# Agent tokens (per-agent access to agent compositor)
# These are pre-generated for external agents connecting via HTTP
agents:
  external-agent-1: "agent_token_xyz789..."
  external-agent-2: "agent_token_def456..."
```

#### Loading Behavior

```python
from pathlib import Path
import os
import yaml

def load_tokens() -> tuple[dict[str, str], dict[str, AgentID]]:
    """Load tokens from config file.

    Returns:
        Tuple of (user_tokens, agent_tokens)
        - user_tokens: token → user_id mapping
        - agent_tokens: token → agent_id mapping
    """
    # Check env override first
    tokens_path = os.getenv("ADGN_TOKENS_FILE")
    if not tokens_path:
        tokens_path = Path.home() / ".config" / "adgn" / "tokens.yaml"
    else:
        tokens_path = Path(tokens_path)

    if not tokens_path.exists():
        return {}, {}

    with open(tokens_path) as f:
        data = yaml.safe_load(f) or {}

    # Invert: file has user_id → token, we want token → user_id
    user_tokens = {token: user_id for user_id, token in data.get("users", {}).items()}
    agent_tokens = {token: AgentID(agent_id) for agent_id, token in data.get("agents", {}).items()}

    return user_tokens, agent_tokens
```

#### Environment Variable Override

- `ADGN_TOKENS_FILE`: Override default token file path

#### Internal Agents (MiniCodex)

Internal agents created via `create_agent()` don't need tokens in the file. They connect via inproc MCP transport which bypasses bearer token routing entirely.

#### External Agents

External agents (e.g., Claude Code connecting remotely) need:
1. Pre-generated token in `tokens.yaml`
2. HTTP URL: `http://host:port/mcp`
3. Bearer token in `Authorization` header

### REST API Removal

**All REST API endpoints will be removed.** Frontend communicates with backend exclusively via MCP.

#### Current REST Endpoints → MCP Replacements

| REST Endpoint | MCP Replacement | Server |
|---------------|-----------------|--------|
| **Agent Management** | | |
| `GET /api/agents` | `agents_list_agents` tool | `agents` |
| `POST /api/agents` | `agents_create_agent` tool | `agents` |
| `DELETE /api/agents/{id}` | `agents_delete_agent` tool | `agents` |
| `GET /api/agents/{id}/status` | `agent_{id}_status` resource | per-agent |
| `GET /api/agents/{id}/snapshot` | `agent_{id}_snapshot` resource | per-agent |
| `GET /api/presets` | `agents_list_presets` tool | `agents` |
| **Agent Control** | | |
| `POST /api/agents/{id}/prompt` | `agent_{id}_agent_control_send_prompt` tool | per-agent |
| `POST /api/agents/{id}/abort` | `agent_{id}_agent_control_abort_run` tool | per-agent |
| **Policy/Approvals** | | |
| `POST /api/agents/{id}/approve` | `agent_{id}_admin_approve_call` tool | per-agent |
| `POST /api/agents/{id}/deny_continue` | `agent_{id}_admin_reject_call` tool | per-agent |
| `POST /api/agents/{id}/deny_abort` | `agent_{id}_admin_reject_call` tool | per-agent |
| `POST /api/agents/{id}/policy` | `agent_{id}_admin_set_policy` tool | per-agent |
| `GET /api/agents/{id}/proposals` | `agent_{id}_reader_proposals` resource | per-agent |
| `POST /api/agents/{id}/proposals/{pid}/withdraw` | `agent_{id}_admin_withdraw_proposal` tool | per-agent |
| `POST /api/agents/{id}/proposals/{pid}/reject` | `agent_{id}_admin_reject_proposal` tool | per-agent |
| `GET /api/agents/{id}/proposals/{pid}` | `agent_{id}_reader_proposal` resource | per-agent |
| **MCP Server Management** | | |
| `POST /api/agents/{id}/mcp/attach` | `agent_{id}_compositor_attach` tool | per-agent |
| `POST /api/agents/{id}/mcp/detach` | `agent_{id}_compositor_detach` tool | per-agent |
| **Runs (Historical)** | | |
| `GET /api/runs` | `agents_list_runs` tool | `agents` |
| `GET /api/runs/{id}` | `agents_get_run` tool | `agents` |
| `GET /api/runs/{id}/events` | `agents_get_run_events` tool | `agents` |

#### Backend Changes

1. **Remove from `app.py`:**
   - All `@app.get("/api/...")` endpoints
   - All `@app.post("/api/...")` endpoints
   - All `@app.delete("/api/...")` endpoints
   - Keep only: `/` (index.html), `/vite.svg`, `/static/*`, `/mcp`

2. **Add to `agents` server (`mcp_bridge/servers/agents.py`):**
   - `list_presets` tool
   - `list_runs`, `get_run`, `get_run_events` tools

3. **Add to per-agent user compositor:**
   - `status` resource
   - `snapshot` resource
   - `compositor_attach`, `compositor_detach` tools (or mount compositor_meta)

#### Frontend Changes

**Delete `api.ts` entirely** - all operations move to MCP client.

### Frontend Updates

#### Current State

The frontend (`adgn/src/adgn/agent/web/`) currently:
- Uses HTTP REST API (`api.ts`) for agent CRUD, snapshots, approvals (**to be removed**)
- Uses MCP SSE client (`client.ts`) connecting to `/mcp` for tool calls/resources
- **No authentication** - direct connection without bearer tokens

#### Required Changes

1. **Delete `api.ts`** - no more REST API calls

2. **Switch to Streamable HTTP Transport** (`src/features/mcp/client.ts`)

The MCP SDK deprecated SSE transport in favor of Streamable HTTP (introduced 2025-03-26).
Use `StreamableHTTPClientTransport` instead of `SSEClientTransport`:

```typescript
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'

export interface McpClientOptions {
  bearerToken: string  // Required: Token from URL query param
}

export class AgentMcpClient {
  static async connect(options: McpClientOptions): Promise<AgentMcpClient> {
    const url = `${window.location.origin}/mcp`

    const transport = new StreamableHTTPClientTransport(new URL(url), {
      requestInit: {
        headers: {
          'Authorization': `Bearer ${options.bearerToken}`
        }
      }
    })

    const client = new Client(
      { name: 'adgn-web', version: '1.0.0' },
      { capabilities: { resources: { subscribe: true } } }
    )

    await client.connect(transport)
    return new AgentMcpClient(client, transport)
  }

  // Tool calls use global compositor prefixes
  async listAgents() {
    return this.callTool('agents_list_agents')
  }

  async createAgent(preset?: string) {
    return this.callTool('agents_create_agent', { preset })
  }

  async bootAgent(agentId: string) {
    return this.callTool('agents_boot_agent', { agent_id: agentId })
  }

  // Per-agent tools use agent_{id}_ prefix
  async sendPrompt(agentId: string, text: string) {
    return this.callTool(`agent_${agentId}_agent_control_send_prompt`, { text })
  }

  async approveCall(agentId: string, callId: string) {
    return this.callTool(`agent_${agentId}_admin_approve_call`, { call_id: callId })
  }
}
```

3. **Token from URL Query Parameter** (`src/shared/auth.ts` - new file)

CLI prints URL like: `http://localhost:8765?token=user_token_abc123`

```typescript
/**
 * Extract bearer token from URL query parameter.
 * CLI provides URL with token embedded: http://host:port?token=...
 */
export function getTokenFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get('token')
}

/**
 * Get token, throwing if not present in URL.
 */
export function requireToken(): string {
  const token = getTokenFromUrl()
  if (!token) {
    throw new Error('Missing token in URL. Launch via CLI to get authenticated URL.')
  }
  return token
}
```

4. **CLI URL Output** (backend `cli.py`)

```python
# When starting server, print authenticated URL:
token = list(load_tokens()[0].values())[0]  # Get first user token
print(f"Open UI: http://{host}:{port}?token={token}")
```

#### Migration Path

1. **Phase 5a**: Backend implements MCP tools/resources for all REST functionality
2. **Phase 5b**: Frontend migrates from api.ts to MCP client calls
3. **Phase 5c**: Remove REST endpoints from app.py
4. **Phase 5d**: CLI prints authenticated URL on startup

#### Browser Session Issue (Known)

There's a known issue in the MCP TypeScript SDK where `mcp-session-id` headers
aren't properly maintained in browser environments. If session continuity issues
arise, may need to implement custom session handling or await SDK fix.
See: [GitHub Issue #852](https://github.com/modelcontextprotocol/typescript-sdk/issues/852)

### Dependencies

- PolicyEngine with `.reader`, `.policy_proposer`, `.admin` servers (✅ Done)
- Compositor with middleware support (✅ Done)
- HTTP/SSE MCP transport on `/mcp` (exists but broken due to missing imports)
- FastMCP TokenVerifier auth (available in fastmcp.server.auth)
