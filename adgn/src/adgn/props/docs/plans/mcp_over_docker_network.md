# MCP Services Over Docker Network

## Overview

**Goal**: Run ALL agent types (prompt-optimizer, critic, grader) in isolated Docker containers that communicate with MCP servers on the host via HTTP.

**Key Insight**: These are NOT concurrent long-running services. They're ephemeral servers launched per agent run:
- **Prompt optimizer agent** (in container) talks to `prompt_eval` MCP server (host, ephemeral)
  - Server has `run_critic()` and `run_grader()` tools that spawn nested agent runs
- **Critic agent** (in container) talks to `critic_submit` MCP server (host, ephemeral)
  - Server provides `submit()` tool for critique submission
- **Grader agent** (in container) talks to `grader_submit` MCP server (host, ephemeral)
  - Server provides `submit()` tool for grading results

**Lifecycle**: ALL MCP HTTP servers are **ephemeral** - launched only during agent runs, not as standalone long-running services.

**Rollout Strategy**: Start with one agent type (e.g., grader) to validate the pattern, then extend to all three.

**Motivation**:
- Run agents in isolated containers (no internet access)
- Standard MCP streamable HTTP transport + bearer tokens (simpler than compositor wiring)
- Agent uses MCP Python SDK client (`streamablehttp_client` with headers support)
- Servers on host have Docker access to spawn agent containers

## Current Architecture (In-Process)

```
Host Machine
└── run_prompt_optimization() Python function
    ├── Creates prompt_eval MCP server (in-proc)
    ├── Spawns prompt-optimizer agent
    └── Agent calls prompt_eval tools:
        ├── run_critic() → spawns critic agent (new compositor)
        └── run_grader() → spawns grader agent (new compositor)
```

**Issues**:
- Prompt-optimizer agent runs on host (has internet access)
- Hard to isolate agent execution
- Complex nested compositor setup

## Proposed Architecture (Docker Network + HTTP)

```
Host Machine
├── All MCP HTTP servers (prompt_eval, critic_submit, grader_submit)
│   └── Servers have Docker access to spawn agent containers
└── [Ephemeral] prompt_eval HTTP server (uvicorn, dynamic port via pick_free_port)
    ├── Launched at start of prompt optimization run
    ├── Shut down when optimization completes
    ├── Tools: upsert_prompt, run_critic, run_grader
    └── run_critic/run_grader spawn critic/grader agents in their own containers

Docker Network (props_default)
├── props-postgres (PostgreSQL - persistent)
├── [Ephemeral] prompt-optimizer-agent-container
│   ├── Talks to prompt_eval server on host (dynamic port)
│   ├── Can reach: gateway IP on props_default network
│   ├── Can reach: props-postgres:5432
│   └── Note: Non-internal network (needed for host access)
├── [Ephemeral] critic-agent-container (spawned by prompt_eval.run_critic)
│   └── Talks to critic_submit server on host (dynamic port)
└── [Ephemeral] grader-agent-container (spawned by prompt_eval.run_grader)
    └── Talks to grader_submit server on host (dynamic port)
```

**Key differences from original plan**:
- Only ONE HTTP server explicitly launched (`prompt_eval`)
- The `run_critic`/`run_grader` tools spawn ephemeral servers (`critic_submit`, `grader_submit`) + agent containers as needed
- All servers run on host; all agents run in isolated containers
- **Servers are ephemeral**: launched on-demand, not long-running services

## Service Specification

### Prompt Eval Server (Ephemeral HTTP Service)

**Host Port**: Dynamically allocated (via `pick_free_port`)
**Server Name**: `prompt_eval`
**Lifecycle**: Launched at start of prompt optimization, shut down at completion
**Purpose**: Expose critic/grader evaluation tools to prompt-optimizer agent

**Tools** (already exist in `build_prompt_eval_server`):
1. `upsert_prompt(file_path: str) -> UpsertPromptOutput`
   - Reads prompt from container workspace
   - Hashes and stores in DB
   - Returns SHA256 for use in run_critic

2. `run_critic(input: CriticInput) -> RunCriticOutput`
   - Spawns critic_submit server on host + critic agent in container
   - Stores critique in DB
   - Returns critic_run_id + critique_id

3. `run_grader(input: GraderInput) -> RunGraderOutput`
   - Spawns grader_submit server on host + grader agent in container
   - Computes TP/FP/FN metrics
   - Stores results in DB
   - Returns grader_run_id

**Implementation** (same pattern for all three agent types):
```python
# src/adgn/props/servers/{prompt_eval|critic_submit|grader_submit}_server.py
def create_*_http_server(workspace_root: Path, auth_token: str | None = None, ...):
    """Create HTTP-exposed MCP server with auth configured."""
    expected_token = auth_token or os.getenv("ADGN_*_TOKEN")
    if not expected_token:
        raise ValueError("Token not set")

    auth = DebugTokenVerifier(
        validate=lambda token: token == expected_token,
        client_id="agent-name",
        scopes=[],
    )

    # Build ONE server with auth configured (no copying tools)
    mcp = build_*_server(
        ...,
        auth=auth,
        instructions="Server-specific workflow instructions here",
    )
    return mcp
```

**Notes**:
- ONE server created per agent type, no tool copying
- Existing `build_*_server()` functions need `auth` and `instructions` parameters
- `run_critic`/`run_grader` tools spawn nested ephemeral servers + containers

### Alternative: MCP Config File (NOT RECOMMENDED)

**Don't use FastMCP's `MCPConfigTransport`** - it has critical limitations:
- ❌ Loses server instructions (only parent router metadata visible)
- ❌ May break notification routing from child servers
- ❌ No advantage over env vars for single-server case
- ❌ Extra file management complexity

**Use direct connection instead**: Environment variables (`MCP_SERVER_URL`, `MCP_SERVER_TOKEN`) with `streamablehttp_client` as shown in main examples.

## Complete Workflow

The full sequence when running prompt optimization:

```
1. Host: Pick free port dynamically (e.g., port 54321)
   └── Use pick_free_port() utility

2. Host: Launch prompt_eval HTTP server (uvicorn :54321)
   └── Server ready at http://localhost:54321

3. Host: Launch agent container (via properties_docker_spec + wiring.attach)
   ├── Network: props_default (shared with postgres)
   ├── Environment: MCP_SERVER_URL=http://host.docker.internal:54321/mcp
   └── Environment: MCP_SERVER_TOKEN=<token>

4. Agent (in container): Connect to MCP server via streamable HTTP
   ├── Read MCP_SERVER_URL and MCP_SERVER_TOKEN from environment
   ├── Connect via streamablehttp_client with bearer token auth
   ├── Introspect server: session.initialize(), session.list_tools()
   └── Call tools: session.call_tool("submit", arguments={...})

5. Agent completes: Container exits

6. Host: Shut down prompt_eval HTTP server
   └── Port 54321 released and available for reuse
```

**Key insights**:
- All agents run in isolated Docker containers (prompt-optimizer, critic, grader)
- All MCP servers run on the host (prompt_eval, critic_submit, grader_submit)
- MCP servers have Docker access to spawn agent containers
- Agent containers talk back to MCP servers on the host via HTTP

## Agent Container Setup

### Dockerfile Changes

Add MCP client libraries:

```dockerfile
# docker/llm/properties-critic/Dockerfile

# Add Python MCP client library (includes streamablehttp_client with bearer token support)
RUN pip install --no-cache-dir \
    mcp>=1.0.0

# No network access to internet
# (Docker default with custom network)
```

### Container Wiring Pattern

We use our existing `properties_docker_spec()` pattern from `adgn.props.docker_env`:

```python
from pathlib import Path
from adgn.props.docker_env import properties_docker_spec
from adgn.mcp.compositor.server import Compositor

# Create Docker wiring spec with MCP HTTP server connection
wiring = properties_docker_spec(
    workspace_root=Path("/path/to/workspace"),
    mount_properties=True,  # Mount property definitions at /props
    ephemeral=True,  # Container removed after use
    workspace_mode="rw",  # Read-write access to workspace
    network_mode="props_default",  # Shared network with postgres
)

# For HTTP mode: Extend ContainerOptions with MCP server connection environment
# This would be added to the environment dict in properties_docker_spec:
# {
#     "MCP_SERVER_URL": f"http://host.docker.internal:{port}/mcp",
#     "MCP_SERVER_TOKEN": os.getenv("ADGN_PROMPT_EVAL_TOKEN"),
#     ... (existing cache/tmp env vars)
# }

# Attach wiring to compositor (this starts the container)
comp = Compositor("compositor")
runtime_server = await wiring.attach(comp)
# Container is now running with all volumes and environment configured
```

**Key points**:
- Use `properties_docker_spec()` to create wiring object
- Add MCP URL/token to environment variables for HTTP mode
- Call `wiring.attach(comp)` to start the container
- Container lifecycle is managed by the MCP exec server (`make_container_exec_server`)
- Network mode `props_default` allows container to reach host via gateway IP

### Agent Code Pattern (Same for All Agent Types)

```python
# Inside any agent container - reads URL/token from environment
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
import os

url = os.getenv('MCP_SERVER_URL')    # Set by host at launch
token = os.getenv('MCP_SERVER_TOKEN')
if not url or not token:
    raise RuntimeError("MCP_SERVER_URL and MCP_SERVER_TOKEN required")

async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read, write, _), \
           ClientSession(read, write) as session:
    # 1. Initialize - get server info/instructions
    init = await session.initialize()

    # 2. List/inspect tools if needed
    tools = await session.list_tools()

    # 3. Call tools
    result = await session.call_tool("submit", arguments={...})
```

**Key points**: No hardcoded URLs; generic env vars work for all agent types; dynamic ports set by host.

### Agent Prompt Strategy

**Minimal prompts**: Server provides instructions via `initialize()`. Agent prompt just needs:
1. Task description
2. Env vars: `$MCP_SERVER_URL`, `$MCP_SERVER_TOKEN`
3. Basic MCP operations (connect, initialize, list_tools, call_tool)

**Template**:
```markdown
**Task**: [e.g., "Review code and submit issues"]

**MCP Server**: Connection in `$MCP_SERVER_URL` and `$MCP_SERVER_TOKEN`.

**Operations**:
1. Connect: `streamablehttp_client(url, headers={'Authorization': f'Bearer {token}'})`
2. Initialize: Get server instructions via `await session.initialize()`
3. List tools: `await session.list_tools()` to discover operations
4. Call tools: `await session.call_tool(name, arguments={...})`

Read server instructions and tool schemas for details.
```

## Server Self-Documentation

Servers provide metadata via `initialize()` and `list_tools()`:
- **Server info**: name, version, `instructions` (workflow description)
- **Tool schemas**: descriptions, parameter types, validation rules via Pydantic `Field(description=...)`

Agents discover everything by introspecting - no need to repeat docs in agent prompts.

## Server Lifecycle (Same Pattern for All Agent Types)

**Ephemeral servers** launched via context manager (same for all three agent types):

```python
@asynccontextmanager
async def launch_mcp_http_server(server_factory_fn, port=None):
    """Launch ephemeral MCP HTTP server, yield port."""
    port = port or pick_free_port()  # Dynamic allocation
    app = server_factory_fn()
    server_task = asyncio.create_task(uvicorn.Server(...).serve())
    try:
        await asyncio.sleep(0.1)
        yield port
    finally:
        server.should_exit = True
        await server_task

# Usage (same for prompt-optimizer, critic, grader)
async def run_*_http(...):
    async with launch_mcp_http_server(lambda: create_*_http_server(...)) as port:
        wiring = properties_docker_spec(
            ...,
            extra_env={
                "MCP_SERVER_URL": f"http://host.docker.internal:{port}/mcp",
                "MCP_SERVER_TOKEN": token,
            },
        )
        await wiring.attach(Compositor("compositor"))
        # Agent runs, server auto-shuts down on exit
```

**Key points**: Dynamic ports via `pick_free_port()`; servers ephemeral (tied to agent run); no port conflicts.

## Authentication & Security

**Tokens**: Generate via `openssl rand -hex 32`, store in `.env.secrets`. Server validates via `DebugTokenVerifier` (see implementation section).

**Network isolation**: `props_default` is a non-internal network (needed for host access). Agents can reach postgres (container-to-container) and host MCP servers (via gateway IP).

## Migration Path

**Phase 1**: Add `USE_MCP_HTTP = False` toggle to each agent runner (critic/grader/prompt_optimizer). Implement `_run_*_http()` alongside existing compositor path. Test both paths, compare results.

**Phase 2**: Flip toggle to `True` by default. Keep compositor as fallback.

**Phase 3**: Remove compositor-embedded servers and toggle code once HTTP is stable.

## Testing

**Unit tests**: TestClient against FastMCP app, verify auth (401 without token, 200 with token).

**Integration tests**: Launch HTTP server + agent container, verify end-to-end via Docker network.

**Manual**: `curl -H "Authorization: Bearer $TOKEN" http://localhost:$PORT/mcp/v1/list_tools`

## Pros/Cons

**Pros**: Standard MCP/HTTP; bearer auth; network isolation; ephemeral servers; dynamic ports; easy testing; observable.

**Cons**: Server lifecycle management; token setup; Docker network config; HTTP latency (negligible).

## Implementation Checklist

### Phase 1: HTTP Infrastructure (Parallel with Compositor)

- [ ] Add global toggle variables to agent launcher modules:
  - [ ] `src/adgn/props/critic_runner.py`: Add `USE_MCP_HTTP = False`
  - [ ] `src/adgn/props/grader_runner.py`: Add `USE_MCP_HTTP = False`
  - [ ] `src/adgn/props/prompt_optimizer_runner.py`: Add `USE_MCP_HTTP = False`
- [ ] Create server module `src/adgn/props/servers/prompt_eval_server.py`
  - [ ] Create ONE server (no copying tools between servers)
  - [ ] Pass `auth=DebugTokenVerifier(...)` to existing builder function
  - [ ] Pass `instructions=...` to builder for comprehensive server description
  - [ ] Ensure existing builder accepts `auth` and `instructions` parameters
  - [ ] Server is ready to serve via uvicorn (streamable-http transport)
- [ ] Create ephemeral server launcher (`launch_mcp_http_server` context manager)
  - [ ] Use `pick_free_port()` to allocate port dynamically
  - [ ] Start uvicorn in background task on allocated port
  - [ ] Yield port number to caller for agent environment variables
  - [ ] Clean shutdown on context exit
- [ ] Update Dockerfile to install MCP Python SDK (`mcp>=1.0.0`)
- [x] Create Docker network setup script (`props_default` - done in devenv.nix)
- [ ] Extend `properties_docker_spec()` to support additional environment variables:
  - [ ] Add `extra_env` parameter (dict) to merge with default cache/tmp env vars
  - [ ] Use this to pass generic `MCP_SERVER_URL` and `MCP_SERVER_TOKEN` to containers
  - [ ] These generic env vars work for all agent types (no agent-specific naming)
- [ ] Implement HTTP code paths in agent launchers:
  - [ ] `_run_critic_http()` in critic_runner.py
  - [ ] `_run_grader_http()` in grader_runner.py
  - [ ] `_run_po_http()` in prompt_optimizer_runner.py
  - [ ] All use dynamic port allocation, ephemeral servers, Docker containers
  - [ ] Environment variables (DB host, MCP URL with dynamic port, token)
  - [ ] Volume mounts (workspace)
- [ ] Update agent prompt templates to use minimal prompt strategy:
  - [ ] Use generic env var names (`MCP_SERVER_URL`, `MCP_SERVER_TOKEN`)
  - [ ] Reference complete MCP usage example (no duplication)
  - [ ] Remove detailed tool documentation (agents introspect server)
  - [ ] Same template works for all three agent types
  - [ ] See "Minimal Agent Prompt Template" section for example
- [ ] Create `.env.secrets` template with `ADGN_PROMPT_EVAL_TOKEN`
- [ ] Write integration tests with toggle support
  - [ ] Server auth tests
  - [ ] Docker network connectivity tests
  - [ ] End-to-end agent workflow tests (both paths)
  - [ ] Server lifecycle tests (startup/shutdown)
  - [ ] Comparison tests (toggle=False vs toggle=True, same results)
- [ ] Update README with new architecture and migration plan

## Open Questions

1. **Rate limiting**: Do we need per-token rate limits?
2. **Logging**: Centralize server logs? (stdout for now)
3. **Which agent to start with**: Grader, critic, or prompt-optimizer? (Recommend grader - simpler workflow)

**Deferred for later:**
- **Token rotation**: Not implementing rotation initially (manual regeneration if needed)
- **TLS**: Localhost-only, plain HTTP is sufficient (no TLS for now)

**Future enhancements:**
- **mcptools server aliases**: The `mcptools` CLI supports server aliases that can embed auth headers. This would allow agents to use short commands like `mcp call tool_name server-alias` instead of passing full URL + auth each time.

  **Config format**: mcptools stores aliases in two ways:
  1. **Server aliases** (via `mcp alias add <name> <command>`): Stored in `~/.mcpt/aliases.json`
  2. **LLM app configs** (via `mcp configs set <app> <server> <command>`): Stored in `~/.mcpt/configs.json` with predefined app names (vscode, cursor, claude-desktop, etc.)

  **Setup options for Docker containers**:
  - **Init script**: Generate config file in container at startup via entrypoint script that creates `~/.mcpt/aliases.json` from environment variables:
    ```json
    {
      "critic-server": "http://host.docker.internal:${PORT}/mcp --headers Authorization=Bearer ${TOKEN}"
    }
    ```
  - **Volume mount**: Mount pre-generated config from host: `--mount type=bind,source=/host/mcpt-config,target=/root/.mcpt,readonly`
  - **Command wrapper**: Create shell function/alias that passes URL + auth without using mcptools config system

  **Current limitation**: Config management CLI commands (`mcp configs set`, `mcp alias add`) only work on macOS; but the *config files* themselves (`~/.mcpt/*.json`) work cross-platform once created.

  **Recommendation**: Use init script approach for simplest cross-platform support. See https://github.com/f/mcptools#server-aliases for config format details.

## References

- FastMCP HTTP transport: https://gofastmcp.com/transports/http
- Docker networking: https://docs.docker.com/network/drivers/bridge/
- MCP authentication: https://spec.modelcontextprotocol.io/specification/architecture/transports/
