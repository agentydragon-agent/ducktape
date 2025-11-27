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

Single `/mcp` endpoint serves both users and agents. Bearer token determines routing to **completely different ASGI applications**:

```
                          ┌─────────────────────────────────────────────┐
                          │              /mcp endpoint                   │
                          │     (same port, same URL for both)          │
                          └─────────────────┬───────────────────────────┘
                                            │
                          ┌─────────────────┴───────────────────────────┐
                          │           TokenRoutingASGI                   │
                          │   (ASGI app that dispatches by token)        │
                          └─────────┬───────────────────────┬───────────┘
                                    │                       │
                    ┌───────────────┴───────┐   ┌───────────┴───────────────┐
                    │   User Token          │   │   Agent Token             │
                    │   → user ASGI app     │   │   → agent_{id} ASGI app   │
                    │   (global compositor) │   │   (agent compositor)      │
                    └───────────────────────┘   └───────────────────────────┘
```

**Key insight**: This is NOT middleware that modifies requests. It's ASGI-level routing where different tokens dispatch to **completely separate FastMCP ASGI apps**, each with their own compositor instance.

### Architecture: User-Facing Compositor (2-level)

```
User-Facing Global Compositor
├── agents (management server, prefix="agents")
│   ├── list resource → agents://agents/list
│   ├── presets resource → agents://agents/presets
│   ├── create_agent tool → agents_create_agent
│   ├── delete_agent tool → agents_delete_agent
│   └── boot_agent tool → agents_boot_agent (lazy mounts per-agent)
│
└── agent_{id} (per-agent user compositor, mounted dynamically)
    ├── reader (policy.py) → agent_{id}_reader_*
    ├── admin (approve/reject/set) → agent_{id}_admin_*
    ├── agent_control (INTERNAL ONLY: send_prompt, abort_run)
    └── status, snapshot resources → agent_{id}://agent_{id}/status
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
   - **Custom ASGI app for routing** (`TokenRoutingASGI`) - FastMCP doesn't route by token natively

2. **Agent lifecycle: `create_agent` vs `boot_agent`**
   - `create_agent(preset)`: Creates NEW agent from preset + boots it immediately
   - `boot_agent(id)`: Boots EXISTING agent that has state in DB (internal agents only)
   - Both mount agent's user compositor to global compositor
   - Uses `asyncio.Lock` for concurrent calls - boot once, others succeed
   - **Does NOT generate tokens** - internal agents use inproc MCP

3. **AgentID type with validation**
   - Use Pydantic `Annotated` for runtime charset validation
   - Safe characters only: `[a-z0-9-]` (lowercase alphanumeric + hyphen)
   - Safe to use as tool prefix: `agent_{id}_send_prompt`
   ```python
   from typing import Annotated
   from pydantic import AfterValidator

   def validate_agent_id(v: str) -> str:
       if not v or not all(c.isalnum() or c == '-' for c in v) or not v[0].isalnum():
           raise ValueError(f"Invalid agent ID: {v!r}")
       return v.lower()

   AgentID = Annotated[str, AfterValidator(validate_agent_id)]
   ```

4. **Unmount on shutdown**
   - When agent shuts down, unmount its user compositor from global
   - Uses Compositor's `unmount_server()` method

5. **Shared PolicyEngine**
   - Single engine per agent, shared between both compositors
   - Both mount same `.reader`, `.policy_proposer`, `.admin` servers

6. **Resource URI prefixing (FastMCP path format)**
   - FastMCP default "path" format: `{scheme}://{path}` → `{scheme}://{prefix}/{path}`
   - Example: `agents://list` mounted with prefix "agents" → `agents://agents/list`
   - Frontend uses prefixed URIs: `agents://agents/list`, `agent_foo://agent_foo/status`
   - Tool names also prefixed: `list_agents` → `agents_list_agents`

7. **Token types**
   - **User tokens**: Pre-generated, stored in `tokens.yaml`, route to global compositor
   - **Agent tokens**: Pre-generated for external agents only, route to that agent's compositor
   - **Internal agents**: Use inproc MCP transport, bypass HTTP/token routing entirely

8. **External agent limitations**
   - External agents can't be controlled via user UI (no `send_prompt`, no `abort_run`)
   - Implemented by not mounting `agent_control` server for external agents
   - User compositor for external agents only mounts: `reader`, `admin`
   - External agent drives itself - user can only view state and approve/reject

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

    async def create_external_agent(self, agent_id: AgentID) -> AgentContainer:
        """Create an external agent's container at startup.

        External agents are created eagerly from tokens config.
        Like boot_agent(), this ALSO mounts user compositor to global
        so the user sees all agents (internal + external) in the same UI.
        """
        async with self._lock:
            if agent_id in self._agents:
                return self._agents[agent_id]
            container = await self._create_container(agent_id, external=True)
            self._agents[agent_id] = container
            # Mount user compositor to global (same as internal agents)
            await self.global_compositor.mount_inproc(
                f"agent_{agent_id}",
                container.user_compositor
            )
            return container
```

#### Step 3: Static Token Verifier

Simple token verifier for static token lookup (FastMCP doesn't have one built-in):

```python
from fastmcp.server.auth import TokenVerifier, AccessToken

class StaticTokenVerifier(TokenVerifier):
    """Simple token verifier for pre-configured static tokens."""

    def __init__(
        self,
        user_tokens: dict[str, str],       # token → user_id
        agent_tokens: dict[str, AgentID],  # token → agent_id
    ):
        super().__init__()
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

**Note**: This verifier is only used if we want FastMCP's auth middleware. For our custom `TokenRoutingASGI`, we do token lookup directly in the ASGI app.

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
from fastmcp.server import create_streamable_http_app
from starlette.applications import Starlette
from starlette.routing import Mount

from adgn.agent.mcp_bridge.compositor_factory import create_global_compositor
from adgn.agent.mcp_bridge.server import InfrastructureRegistry
from adgn.agent.mcp_bridge.auth import TokenRoutingASGI, load_tokens

async def lifespan(app):
    # Load tokens at startup
    user_tokens, agent_tokens = load_tokens()

    # Create infrastructure registry
    registry = InfrastructureRegistry(
        persistence=...,
        docker_client=...,
        mcp_config=...,
        initial_policy=...,
    )

    # Create global user-facing compositor
    global_comp = await create_global_compositor(registry)
    registry.global_compositor = global_comp

    # Create external agent containers at startup
    # This mounts their user compositors to global_comp
    agent_apps: dict[AgentID, ASGIApp] = {}
    for agent_id in set(agent_tokens.values()):
        # Creates container AND mounts user compositor to global
        container = await registry.create_external_agent(agent_id)
        # Agent ASGI app for the agent's HTTP connection (with policy gateway)
        agent_apps[agent_id] = create_streamable_http_app(container.agent_compositor)

    # Create ASGI app for user compositor (now includes external agent prefixes)
    user_app = create_streamable_http_app(global_comp)

    # Build token routing app
    mcp_app = TokenRoutingASGI(
        user_tokens=user_tokens,
        agent_tokens=agent_tokens,
        user_app=user_app,
        agent_apps=agent_apps,
    )

    # Store for route mounting
    app.state.mcp_app = mcp_app
    app.state.registry = registry

    yield

    # Shutdown
    await registry.shutdown_all()

# Starlette app with /mcp mounted to token router
app = Starlette(
    lifespan=lifespan,
    routes=[
        Mount("/mcp", app=lambda: app.state.mcp_app),
        # Static files, etc.
    ],
)
```

### Implementation Flow

```
USER FLOW (Internal Agents):
1. User connects with user bearer token
   → TokenRouter routes to global_compositor
   → User sees: agents server + any booted agent_{id} sub-compositors

2. User calls: agents_boot_agent(id="abc123")
   - InfrastructureRegistry.boot_agent() acquires lock
   - Creates AgentContainer (agent_compositor + user_compositor)
   - Mounts user_compositor as "agent_abc123" on global
   - Agent uses inproc MCP (no HTTP token needed)

3. User can now call (via global compositor):
   - agent_abc123_agent_control_send_prompt(text="Hello")
   - agent_abc123_agent_control_abort_run()
   - agent_abc123_admin_approve_call(call_id="...")

4. User subscribes to agents://list resource for real-time updates
   (notifications when agents boot/shutdown/change state)

EXTERNAL AGENT FLOW:
5. External agent has pre-generated token in tokens.yaml
   → TokenRouter routes to that agent's agent_compositor
   → Agent sees: reader, policy_proposer, ui, chat, loop, runtime
   → All tool calls gated by policy gateway middleware

6. Agent calls tools (e.g., runtime_exec)
   → Policy gateway middleware intercepts
   → Evaluates policy in Docker container
   → Allow/deny/ask decision
```

### Notes

- **No existing bearer token code on devel** - needs full implementation
- **FastMCP auth**: No built-in `StaticTokenVerifier` - implement our own (see Step 3)
- **Routing by token**: FastMCP doesn't support this natively; custom `TokenRoutingASGI` required
- **Resource notifications**: Use FastMCP's `notify_resource_updated()` for real-time updates

### FastMCP Auth Integration

FastMCP provides token verification but not token-based routing to different servers:

```python
from fastmcp.server.auth import StaticTokenVerifier, AccessToken

# StaticTokenVerifier: maps token strings to claims
verifier = StaticTokenVerifier(
    tokens={
        "user_token_abc": {"client_id": "admin", "scopes": ["user"]},
        "agent_token_xyz": {"client_id": "agent-1", "scopes": ["agent"]},
    }
)

# Verification only - returns AccessToken or None
token_info = await verifier.verify_token("user_token_abc")
# AccessToken(token="...", client_id="admin", scopes=["user"], ...)
```

**ASGI-level routing required:**

FastMCP creates a separate ASGI app per compositor via `create_streamable_http_app()`.
We need custom ASGI routing to dispatch requests to different ASGI apps based on bearer token:

```python
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import Response

class TokenRoutingASGI:
    """ASGI app that routes /mcp requests to different MCP servers based on bearer token.

    This is NOT middleware - it's a top-level ASGI app that dispatches to
    completely different ASGI applications based on the token.
    """

    def __init__(
        self,
        user_tokens: dict[str, str],           # token → user_id
        agent_tokens: dict[str, AgentID],      # token → agent_id
        user_app: ASGIApp,                     # ASGI app for user compositor
        agent_apps: dict[AgentID, ASGIApp],    # ASGI apps for agent compositors
    ):
        self.user_tokens = user_tokens
        self.agent_tokens = agent_tokens
        self.user_app = user_app
        self.agent_apps = agent_apps

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Passthrough for lifespan, websocket, etc.
            await self.user_app(scope, receive, send)
            return

        # Extract Authorization header
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()

        if not auth.startswith("Bearer "):
            response = Response("Unauthorized", status_code=401)
            await response(scope, receive, send)
            return

        token = auth[7:]

        # Route based on token
        if token in self.user_tokens:
            await self.user_app(scope, receive, send)
        elif token in self.agent_tokens:
            agent_id = self.agent_tokens[token]
            agent_app = self.agent_apps.get(agent_id)
            if agent_app is None:
                response = Response("Agent not found", status_code=404)
                await response(scope, receive, send)
                return
            await agent_app(scope, receive, send)
        else:
            response = Response("Invalid token", status_code=401)
            await response(scope, receive, send)
```

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

#### Startup Behavior

External agent containers are created at startup from tokens config. See **Step 6: app.py** for full implementation.

**Startup sequence:**
1. Load tokens from `tokens.yaml`
2. Create global user-facing compositor (with `agents` server mounted)
3. For each external agent token:
   - Create `AgentContainer` (user compositor + agent compositor with policy gateway)
   - Mount user compositor to global as `agent_{id}` (NO agent_control - external can't be controlled)
4. Create ASGI apps: one for global compositor, one per external agent's agent compositor
5. Build `TokenRoutingASGI` with all ASGI apps
6. Mount at `/mcp` endpoint

**Internal vs External agents:**
- **Internal**: Created lazily via `create_agent()`/`boot_agent()`, use inproc MCP (no HTTP token)
- **External**: Created at startup, connect via HTTP with agent token
- **Both**: User compositor mounted on global → user sees all agents in same UI

### REST API Removal

**All REST API endpoints will be removed.** Frontend communicates with backend exclusively via MCP.

#### Current REST Endpoints → MCP Replacements

| REST Endpoint | MCP Replacement | Notes |
|---------------|-----------------|-------|
| **Agent Management** | | |
| `GET /api/agents` | `agents://agents/list` resource | Prefixed URI |
| `POST /api/agents` | `agents_create_agent` tool | |
| `DELETE /api/agents/{id}` | `agents_delete_agent` tool | |
| `GET /api/agents/{id}/status` | `agent_{id}://agent_{id}/status` resource | Per-agent prefixed |
| `GET /api/agents/{id}/snapshot` | `agent_{id}://agent_{id}/snapshot` resource | Per-agent prefixed |
| `GET /api/presets` | `agents://agents/presets` resource | Prefixed URI |
| **Agent Control (internal agents only)** | | |
| `POST /api/agents/{id}/prompt` | `agent_{id}_agent_control_send_prompt` tool | |
| `POST /api/agents/{id}/abort` | `agent_{id}_agent_control_abort_run` tool | |
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
| `GET /api/runs` | `runs://list` resource | `agents` |
| `GET /api/runs/{id}` | `runs://{id}` resource | `agents` |
| `GET /api/runs/{id}/events` | `runs://{id}/events` resource | `agents` |

#### Backend Changes

1. **Remove from `app.py`:**
   - All `@app.get("/api/...")` endpoints
   - All `@app.post("/api/...")` endpoints
   - All `@app.delete("/api/...")` endpoints
   - Keep only: `/` (index.html), `/vite.svg`, `/static/*`, `/mcp`

2. **Add to `agents` server (`mcp_bridge/servers/agents.py`):**
   - `list` resource → exposed as `agents://agents/list` (after mount prefixing)
   - `presets` resource → exposed as `agents://agents/presets`
   - `runs://list`, `runs://{id}`, `runs://{id}/events` resources

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

  // Resources for read operations (use prefixed URIs)
  async listAgents() {
    return this.readResource('agents://agents/list')
  }

  async listPresets() {
    return this.readResource('agents://agents/presets')
  }

  // Tools for mutations
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
- Streamable HTTP MCP transport on `/mcp` (FastMCP supports via `create_streamable_http_app`) (✅ Available)
- FastMCP `StaticTokenVerifier` for token validation (✅ Available)
- Custom ASGI app for token-based routing (`TokenRoutingASGI`) (⏳ Needs implementation)
- External agent compositor startup from tokens config (⏳ Needs implementation)
