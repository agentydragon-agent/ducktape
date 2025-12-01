# Design: Resource Capability Tokens for Agent Collaboration

## Problem

Critics need to spawn sub-agents and share resources (transcripts, MCP servers, volumes) without breaking isolation. Requirements:

1. **Transcript access**: Agents should only see outputs of agents they spawned (or were delegated access to)
2. **MCP server delegation**: Pass server handles between agents (e.g., Docker container access, seatbelt exec)
3. **Resource sharing**: Share read-only volumes/folders across subagent invocations (DRY for utility scripts)
4. **Hierarchical spawning**: Sub-critics spawning their own helpers
5. **Free-text chat**: Bidirectional communication between agents
6. **Future extensibility**: K8s scopes, database connections, external service tokens

## Architecture Context

**Current stack**:
- **Persistence**: **PostgreSQL** with tables: `prompts` (SHA256-keyed), `prompt_optimization_runs`, `critic_runs`, `grader_runs`, `critiques`, `specimens`
  - `critic_runs.transcript_id` + `grader_runs.transcript_id` currently tracked (UUID, indexed) — **will be renamed to `agent_id`** in migration
  - Prompts content-addressed via `prompt_sha256` (primary key)
- **Agent lifecycle**: Actor-based `AgentContainer` with async message queue
- **MCP infrastructure**: `Compositor` pattern aggregates servers, mounts per-agent
- **MCP tools pattern**: **Flat Pydantic models** (`@mcp.flat_model()` / `@mcp.tool(flat=True)`)
  - Input: Single Pydantic `BaseModel` (e.g., `UpsertIssueInput`)
  - Output: Pydantic model or simple type (e.g., `UpsertPromptOutput`, `str`)
- **Isolation**: Agents isolated by `agent_id`; no cross-agent visibility (yet)

**Key files**:
- `src/adgn/props/db/models.py` - SQLAlchemy models (`Prompt`, `PromptOptimizationRun`, `CriticRun`, `GraderRun`, ...)
- `src/adgn/agent/runtime/container.py` - AgentContainer actor (150+ line init, god object)
- `src/adgn/mcp/compositor/server.py` - Compositor (mount/unmount servers, notify on changes)
- `src/adgn/agent/agent.py` - MiniCodex agent (MCP client, handlers, transcript)

## Solution: Resource Capability Tokens

### Core Concept

**Capability token**: An opaque, unforgeable reference (UUID) that grants access to a **resource** (not just an agent). Resources include:
1. **Agent transcripts** (read messages, send follow-ups)
2. **MCP servers** (call tools on a specific server instance)
3. **Volumes/folders** (read-only mounts for shared utilities)
4. **Future**: K8s scopes, database connections, external service credentials

### Token Structure

Each token maps to a **capability record** server-side:
```python
@dataclass
class Capability:
    token: str  # UUID (opaque, unguessable)
    resource_type: Literal["agent", "mcp_server", "volume", ...]
    resource_id: str  # agent_id, server_name, volume_path, etc.
    permissions: set[str]  # {"read", "write", "execute", ...}
    granted_by: str  # Parent agent_id (for cascading cleanup)
    expires_at: datetime | None = None  # Future: time-bound access
```

### Access Model (Agent Transcript Tokens)

**Token**: An opaque UUID that grants:
- **Read access**: Full transcript history + streaming new messages
- **Write access**: Send follow-up messages to the agent
- **Status access**: Check completion state, retrieve final result

**Lifecycle**:
1. Agent A calls `spawn_subagent({prompt, config, ...})`
2. System creates agent B and generates `token_B`
3. System returns `{agent_id: "B", token: token_B}` to A
4. A stores `token_B` and can now:
   - `read_transcript(token_B)` → see B's work
   - `send_message(token_B, "follow up question")` → interact with B
   - `await_completion(token_B)` → block until B finishes
5. A can pass `token_B` in a message to agent C
6. C can now use `token_B` with the same tools

**Security invariants**:
- Tokens are UUIDs (unguessable)
- No "list all agents" API
- No privilege escalation (tokens only grant what spawner had)
- Tokens are revoked when parent session ends (cascade)

### MCP Server: `subagents`

#### Tools (Flat Pydantic Pattern)

Following your established pattern (`@mcp.tool(flat=True)`), all tools use flat Pydantic I/O.

**Phase 1a (MVP - Blocking/Synchronous)**:

```python
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID

# ---- Run subagent (blocking) ----
class RunSubagentInput(BaseModel):
    """Run a subagent to completion (blocking operation)."""
    prompt: str = Field(description="Initial prompt/task for subagent")
    model: str = Field(default="claude-sonnet-4.5", description="LLM model")
    mcp_config: dict = Field(default_factory=dict, description="MCP servers config (mcpServers dict)")
    timeout_secs: int = Field(default=300, description="Max runtime before timeout")
    # Future: prompt_sha256, specimen_slug for auto-linking to props DB

    model_config = ConfigDict(extra="forbid")

class RunSubagentOutput(BaseModel):
    """Subagent result after completion."""
    status: str = Field(description="Completion status: complete|timeout|error")
    final_result: dict | None = Field(default=None, description="Structured output from final tool call")
    agent_id: UUID = Field(description="Postgres agent_id (for DB queries)")
    messages: list[dict] = Field(description="Full transcript (OpenAI-style messages)")
    message_count: int = Field(description="Total messages in transcript")
    error: str | None = Field(default=None, description="Error message if status=error")

@mcp.tool(flat=True)
async def run_subagent(input: RunSubagentInput) -> RunSubagentOutput:
    """Spawn subagent, wait for completion, return result (all in one call).

    Perfect drop-in replacement for current run_critic/grade_critique_by_id patterns.
    """
    ...
```

**Phase 1b (Eventual - Async/Token-based)**:

```python
# ---- Spawn subagent (non-blocking) ----
class SpawnSubagentInput(BaseModel):
    """Spawn a new subagent and receive access token (non-blocking)."""
    prompt: str = Field(description="Initial prompt/task for subagent")
    model: str = Field(default="claude-sonnet-4.5", description="LLM model")
    mcp_config: dict = Field(default_factory=dict, description="MCP servers config (mcpServers dict)")
    parent_token: str | None = Field(default=None, description="Parent token for nested spawning")
    timeout_secs: int = Field(default=300, description="Max runtime before auto-timeout")

    model_config = ConfigDict(extra="forbid")

class SpawnSubagentOutput(BaseModel):
    """Subagent spawn result with access token."""
    token: str = Field(description="Capability token (UUID) - use for await/read/send")
    agent_id: UUID = Field(description="Postgres agent_id (for DB queries)")
    status: str = Field(description="Agent status: starting|ready")

@mcp.tool(flat=True)
async def spawn_subagent(input: SpawnSubagentInput) -> SpawnSubagentOutput:
    """Spawn subagent and return immediately (non-blocking).

    Use for parallel execution: spawn N agents, then await all.
    """
    ...

# ---- Await completion (blocking) ----
class AwaitCompletionInput(BaseModel):
    """Block until subagent completes or times out."""
    token: str = Field(description="Capability token from spawn_subagent")
    timeout_secs: int = Field(default=300, description="Max wait time")

    model_config = ConfigDict(extra="forbid")

class AwaitCompletionOutput(BaseModel):
    """Completion result with final output."""
    status: str = Field(description="Completion status: complete|timeout|error")
    final_result: dict | None = Field(default=None, description="Structured output from final tool call")
    message_count: int = Field(description="Total messages in transcript")
    agent_id: UUID = Field(description="Postgres agent_id for DB queries")
    error: str | None = Field(default=None)

@mcp.tool(flat=True)
async def await_completion(input: AwaitCompletionInput) -> AwaitCompletionOutput:
    """Block until subagent completes (pair with spawn_subagent)."""
    ...

# ---- Read transcript (optional) ----
class ReadTranscriptInput(BaseModel):
    """Read agent transcript (historical + current)."""
    token: str = Field(description="Capability token")
    since_index: int | None = Field(default=None, description="Incremental reads (skip first N)")

    model_config = ConfigDict(extra="forbid")

class ReadTranscriptOutput(BaseModel):
    """Transcript messages + completion state."""
    messages: list[dict] = Field(description="OpenAI-style messages")
    is_complete: bool
    final_result: dict | None = None

@mcp.tool(flat=True)
async def read_transcript(input: ReadTranscriptInput) -> ReadTranscriptOutput:
    """Read subagent transcript without blocking (polling/inspection)."""
    ...

# ---- Send message (optional, for chat) ----
class SendMessageInput(BaseModel):
    """Send follow-up message to running agent."""
    token: str = Field(description="Capability token")
    message: str = Field(description="User message content")

    model_config = ConfigDict(extra="forbid")

class SendMessageOutput(BaseModel):
    """Message sent confirmation."""
    message_index: int = Field(description="Position in transcript")
    agent_status: str = Field(description="running|complete|error")

@mcp.tool(flat=True)
async def send_message(input: SendMessageInput) -> SendMessageOutput:
    """Send follow-up message (for chat/bidirectional use case)."""
    ...

# ---- Fork at checkpoint (efficient parallelization) ----
class ForkAndContinueInput(BaseModel):
    """Fork parent agent N times, each with different continuation."""
    continuations: list[str] = Field(
        min_length=1,
        description="List of continuation messages (one per fork). Each fork inherits parent transcript + gets one message."
    )
    timeout_secs: int = Field(default=300, description="Timeout per fork")

    model_config = ConfigDict(extra="forbid")

class ForkAndContinueOutput(BaseModel):
    """Fork results with tokens for each child."""
    tokens: list[str] = Field(description="Capability tokens (one per fork, same order as continuations)")
    agent_ids: list[UUID] = Field(description="Postgres agent_ids for each fork")

@mcp.tool(flat=True)
async def fork_and_continue(input: ForkAndContinueInput) -> ForkAndContinueOutput:
    """Fork parent agent N times with different continuations.

    Each fork:
    - Inherits parent's full transcript (all previous messages)
    - Inherits parent's MCP servers + capabilities
    - Receives one continuation message from the input list
    - Runs independently from that point

    Use for efficient parallelization without repeating context N times.
    Example: Prompt optimizer forks for each train specimen instead of spawning N fresh critics.
    """
    ...

# ---- Await many (blocking, for fork results) ----
class AwaitManyInput(BaseModel):
    """Block until all subagents complete or timeout."""
    tokens: list[str] = Field(min_length=1, description="Capability tokens to wait for")
    timeout_secs: int = Field(default=300, description="Max wait time per agent")

    model_config = ConfigDict(extra="forbid")

class AwaitManyOutput(BaseModel):
    """Completion results for all subagents."""
    results: list[dict] = Field(description="List of completion results (one per token, same order)")
    # Each result: {status, final_result, message_count, agent_id, error}

@mcp.tool(flat=True)
async def await_many(input: AwaitManyInput) -> AwaitManyOutput:
    """Block until all subagents complete (parallel wait).

    Pair with fork_and_continue or spawn_subagent for batch operations.
    """
    ...
```

#### Resources

```
resource://subagents/active
  → JSON list of active agent_ids (for current session only; no cross-session visibility)

resource://subagents/{token}/transcript
  → Live transcript view (useful for UI, updates on ResourceUpdated)
```

### Implementation: Server-Side State

```python
# Capability registry (in-memory, per MiniCodex backend instance)
@dataclass
class AgentCapability:
    agent_id: str
    token: str  # UUID
    spawned_by: str  # Parent agent_id (for cascading cleanup)
    created_at: datetime

    # Future: separate read/write tokens, expiration, revocation

# Storage
capabilities: dict[str, AgentCapability]  # token → capability
active_agents: dict[str, AgentRuntime]    # agent_id → runtime

# Access validation
def validate_token(token: str) -> AgentCapability:
    """Raises ToolError if token invalid/expired."""
    if token not in capabilities:
        raise ToolError("invalid token", code="INVALID_TOKEN")
    return capabilities[token]

# Cleanup
def cleanup_agent_cascade(agent_id: str):
    """Remove agent + all subagents it spawned."""
    # Find all tokens spawned by this agent
    child_tokens = [
        cap for cap in capabilities.values()
        if cap.spawned_by == agent_id
    ]
    # Recursive cleanup
    for child_cap in child_tokens:
        cleanup_agent_cascade(child_cap.agent_id)
    # Remove this agent
    del active_agents[agent_id]
    # Revoke token
    token = next(t for t, c in capabilities.items() if c.agent_id == agent_id)
    del capabilities[token]
```

### Integration with Properties/Critics

#### Critic Tool Addition

Add `subagents` MCP server to critic containers (alongside `runtime`, `resources`, etc.).

#### Example: Sub-Critic Pattern

```python
# Critic runbook (Jinja2 template, rendered to system prompt)
"""
You are reviewing a Python codebase for dead code.

Steps:
1. Use vulture to find candidates
2. For complex modules, spawn a sub-critic to analyze reachability
3. Aggregate findings

Tools available:
- runtime/exec: Run vulture
- subagents/spawn_subagent: Spawn focused sub-critic
- subagents/read_transcript: Read sub-critic analysis
- critic_submit: Submit final findings
"""

# Critic execution (pseudo-code agent transcript)
# [1] Critic runs vulture
runtime.exec(["vulture", "/workspace", "--min-confidence", "60"])

# [2] Critic sees complex module, spawns sub-critic
result = subagents.spawn_subagent({
    "prompt": "Analyze src/complex_module.py for reachability via imports",
    "config": {"model": "claude-sonnet-4.5", "max_tokens": 8000}
})
# result.token = "550e8400-e29b-41d4-a716-446655440000"

# [3] Critic waits for sub-critic
subagents.await_completion({"token": result.token, "timeout_secs": 120})

# [4] Critic reads sub-critic findings
transcript = subagents.read_transcript({"token": result.token})
# transcript.messages = [..., {"role": "assistant", "content": "Analysis: ..."}]

# [5] Critic aggregates
critic_submit({"issues": [...]})
```

#### Example: Chat Use Case

```python
# Agent A spawns Agent B for discussion
token_b = subagents.spawn_subagent({
    "prompt": "You are a Python expert. Discuss design patterns.",
    "config": {…}
}).token

# A sends initial message
subagents.send_message({"token": token_b, "message": "What's your take on dependency injection?"})

# A reads response
transcript = subagents.read_transcript({"token": token_b, "since_index": 0})
# transcript.messages[-1].content = "Dependency injection is..."

# A continues conversation
subagents.send_message({"token": token_b, "message": "How does that apply to FastAPI?"})

# A can also spawn Agent C and give C access to B
token_c = subagents.spawn_subagent({
    "prompt": f"Review this discussion (access token: {token_b}). Summarize key points.",
    "config": {…}
}).token

# Agent C now reads B's transcript using token_b (passed in its prompt)
```

### Access Hierarchy Enforcement

**Server-side validation**:
```python
def read_transcript(token: str) -> TranscriptResult:
    cap = validate_token(token)  # Raises if invalid
    agent = active_agents.get(cap.agent_id)
    if not agent:
        raise ToolError("agent not found", code="AGENT_GONE")
    return TranscriptResult(
        agent_id=cap.agent_id,
        messages=agent.get_messages(),
        is_complete=agent.is_complete,
        final_result=agent.final_result if agent.is_complete else None
    )
```

**Key insight**: The server doesn't track "who is calling"; it only validates tokens. If you have a valid token, you have access. This makes delegation trivial (just include the token in a message).

### Token Lifecycle & Cleanup

**Creation**: `spawn_subagent` generates UUID, stores in `capabilities` dict

**Usage**: Any tool call with the token reads from `capabilities`

**Revocation scenarios**:
1. **Parent disconnect**: When parent agent session ends, cascade delete all child tokens
2. **Explicit revoke** (future): `revoke_token(token)` tool
3. **Expiration** (future): Time-bound tokens with TTL

**Garbage collection**:
```python
async def cleanup_session(session_id: str):
    """Called when a MiniCodex session disconnects."""
    # Find root agent for this session
    root_agent_id = session_to_agent[session_id]
    # Cascade cleanup (subagents, sub-subagents, etc.)
    cleanup_agent_cascade(root_agent_id)
```

### Future Enhancements

1. **Separate read/write tokens**: `spawn_subagent` returns `{read_token, write_token}`, allow read-only delegation
2. **Token revocation**: Explicit `revoke_token(token)` tool
3. **Time-bound access**: Tokens with expiration (`valid_until: datetime`)
4. **Audit log**: Track token usage (who read what, when)
5. **Resource limits**: Spawn depth limits, token count limits per agent
6. **Cross-session sharing**: Allow tokens to outlive parent session (with explicit grant)

## Implementation Plan

### Phase 1: Core Server (MVP)
- [ ] `subagents` MCP server scaffolding (FastMCP)
- [ ] In-memory capability registry
- [ ] Tools: `spawn_subagent`, `read_transcript`, `send_message`, `await_completion`
- [ ] Token validation + error handling
- [ ] Basic cleanup (manual trigger)

### Phase 2: Lifecycle
- [ ] Session tracking (link subagents to parent session)
- [ ] Cascade cleanup on parent disconnect
- [ ] Status resource (`resource://subagents/active`)
- [ ] Unit tests (token validation, cleanup, access control)

### Phase 3: Integration
- [ ] Mount `subagents` server in critic containers
- [ ] Update critic runbook examples/docs
- [ ] E2E test: critic spawns sub-critic, aggregates findings
- [ ] UI: Display subagent tree (parent → children)

### Phase 4: Chat & Delegation
- [ ] Refined `send_message` (bidirectional chat)
- [ ] Example: Multi-agent discussion pattern
- [ ] Token serialization format (for embedding in prompts)
- [ ] E2E test: Agent A → Agent B → Agent C delegation chain

### Phase 5: Advanced (Future)
- [ ] Separate read/write tokens
- [ ] Explicit revocation
- [ ] Time-bound tokens
- [ ] Audit log/telemetry
- [ ] Cross-session token persistence (opt-in)

## Security Considerations

1. **Token entropy**: UUIDs provide ~122 bits (uuid4), sufficient for unguessability
2. **No ambient authority**: Agents can't enumerate other agents without tokens
3. **Cascading revocation**: Parent disconnect cleans up children (prevents orphans)
4. **No privilege escalation**: Tokens grant fixed capabilities; no "upgrade to admin"
5. **Server-side validation**: All access checks server-side; clients can't forge tokens

## Open Questions

1. **Token format**: Plain UUID vs. structured (e.g., `agent:{id}:{secret}`)? → **Plain UUID** (simpler)
2. **Read/write split**: One token or two? → **One token for MVP** (split later if needed)
3. **Nested config**: Should subagents inherit parent's MCP config? → **No, explicit config required** (more control)
4. **Transcript format**: OpenAI messages vs. custom? → **OpenAI messages** (familiar, tooling exists)
5. **Streaming**: WebSocket for live transcript? → **Polling for MVP** (simpler), WebSocket later

## Alternative Approaches Considered

### 1. PostgreSQL Row-Level Security (RLS)

**Approach**: Postgres user per agent, permission grants via RLS policies.

```sql
-- Per-agent user
CREATE USER agent_abc123;

-- RLS policy: agents can only see their own data
CREATE POLICY agent_isolation ON agents
  FOR SELECT USING (id = current_user);

-- Grant access to subagent transcript
GRANT SELECT ON runs TO agent_xyz789
  WHERE agent_id = 'subagent_456';
```

**Benefits**:
- Database-native enforcement (impossible to bypass in app code)
- Auditable (Postgres logs all access)
- Standard pattern (well-understood security model)
- Automatic revocation on user drop

**Drawbacks**:
- **Migration cost**: Requires switching from SQLite to Postgres (schema migration, connection pooling, deployment complexity)
- **Connection overhead**: Each agent needs a dedicated Postgres connection (connection pooling gets complex with per-user auth)
- **User management**: Creating/dropping Postgres users on agent spawn/cleanup adds operational burden
- **Limited to DB**: Doesn't extend to MCP servers, volumes, or non-DB resources
- **Cross-agent delegation**: Requires dynamic GRANT statements (doesn't fit "token in prompt" pattern)

**Verdict**: **Hybrid approach worth evaluating**. Since you already have Postgres partially deployed, RLS could handle the **database portion** (agent transcripts, run metadata, approvals) with native enforcement, while **tokens handle non-DB resources** (MCP servers, volumes, K8s scopes).

**Hybrid design**:
- **DB access**: Postgres RLS (agent users + row-level policies)
  - `CREATE USER agent_abc123; GRANT SELECT ON runs TO agent_abc123 WHERE agent_id IN (SELECT child_id FROM agent_grants WHERE parent_id = 'abc123')`
  - Automatic cascade on user drop
  - Auditable (Postgres logs)
- **Non-DB resources**: Token-based (MCP servers, volumes, etc.)
  - Same UUID token model
  - Server-side registry maps token → resource handle

**Trade-offs**:
- **Pro**: **No MCP tools for DB queries** - agent gets Postgres credentials directly, writes arbitrary SQL in container
  - Eliminates need for `run_query(sql)`, `get_critique(id)`, `list_runs()` MCP tools
  - Agent has full DB power (joins, aggregations, CTEs, window functions)
  - RLS enforces boundaries (agent sees only its data + granted tokens)
- **Pro**: Defense-in-depth for DB (impossible to bypass RLS in Python code)
- **Pro**: Leverage existing Postgres investment
- **Pro**: Agents can be long-lived or dormant (roles persist until explicit cleanup)
- **Con**: Two access models (RLS for DB, tokens for MCP/volumes) adds complexity
- **Con**: User management overhead (CREATE/DROP roles per agent)
  - Low concurrency expected, so connection pooling (PgBouncer) can be deferred
  - Roles may be long-lived (agents can sleep/revive), so no automatic sweeping needed

**Decision**: **Hybrid approach recommended**:
1. **Phase 1 (MVP)**: Token-only (simpler, works immediately with existing Postgres)
2. **Phase 2 (RLS)**: Add RLS policies + per-agent roles, give agents direct DB credentials
   - Agents query DB directly (no MCP wrapper tools)
   - RLS enforces `agent_id IN (SELECT agent_id FROM agent_grants WHERE grantee = current_user)`
   - Tokens remain for MCP servers/volumes (non-DB resources)

**Key insight**: RLS isn't just security—it's **API simplification**. Instead of building MCP tools for every query pattern, give the agent SQL and let the database enforce access.

---

### 2. Cryptographic Capability Tokens (Macaroons/JWTs)

**Approach**: Self-contained signed tokens with embedded claims.

```python
# Token structure (JWT example)
{
  "sub": "agent_xyz789",  # Subject (which agent)
  "cap": "transcript",     # Capability type
  "res": "agent_abc123",   # Resource ID
  "perms": ["read", "write"],
  "exp": 1735689600,       # Expiration
  "iss": "agent_abc123",   # Issuer (granter)
  "sig": "..."             # HMAC or public key signature
}
```

**Benefits**:
- **Truly unforgeable**: Cryptographic guarantee (can't be guessed or brute-forced)
- **Stateless validation**: No server-side lookup required (just verify signature)
- **Delegatable**: Attenuate permissions (add restrictions) when passing to others
- **Distributed systems**: Works across services (no shared database needed)

**Drawbacks**:
- **Revocation is hard**: Can't revoke a token without maintaining a blacklist (defeats statelessness)
- **Key management**: Need secure key storage, rotation policies, compromise recovery
- **Overkill**: For in-memory, single-process agent container, cryptographic signing adds complexity without benefit
- **Size**: JWT tokens can be large (base64-encoded JSON + signature), awkward in prompts

**Verdict**: **Overkill for now**. Crypto tokens shine in distributed systems with untrusted intermediaries (e.g., microservices passing tokens across network boundaries). Our agent containers are in-process, short-lived, and have a shared trust domain (all agents in one Python process). Use simple UUIDs + server-side validation instead. Revisit if we need cross-service agent communication or zero-trust architecture.

---

### 3. Parent-child pointers (no tokens)
- Each agent has `parent_id`, can read children by ID
- **Rejected**: No delegation (can't give sibling access)

### 4. Unix-style file descriptors
- Numeric handles into a handle table
- **Rejected**: Less intuitive than UUIDs; hard to serialize in prompts

### 5. Centralized "agent manager" with ACLs
- Explicit ACL table: `(agent_id, accessor_id) → permissions`
- **Rejected**: Requires knowing accessor identity; breaks delegation model

## Current Use Cases (Immediate Unification)

### 1. Critic Runs (Codebase Analysis)

**Current pattern** (`src/adgn/props/critic.py`, `prompt_optimizer.py`):
```python
# Ad-hoc: manually build compositor + agent
async def run_critic(specimen, prompt_sha256, ...):
    compositor = Compositor("critic")
    # Mount servers: docker exec, critic_submit, resources, ...
    await compositor.mount_server("runtime", properties_docker_spec(...))
    # Build critic_submit server with state
    critic_state = CriticSubmitState(...)
    critic_server = make_critic_submit_server(critic_state)
    await compositor.mount_inproc("critic_submit", critic_server)
    # ... mount 5+ other servers

    # Create agent
    async with Client(compositor) as client:
        agent = await MiniCodex.create(client, handlers=[...])
        result = await agent.run(prompt)

    # Extract structured output from state
    return critic_state.work  # CriticSubmitPayload
```

**With subagents (Phase 1a - blocking)**:
```python
# Agent MCP call (what agents actually do):
"""
result = subagents.run_subagent({
    "prompt": "Review this codebase for dead code...",
    "mcp_config": {
        "mcpServers": {
            "runtime": {"...": "..."},
            "critic_submit": {"...": "..."}
        }
    },
    "timeout_secs": 300
})
# result = {
#     "status": "complete",
#     "final_result": {
#         "issues": [...],  # CriticSubmitPayload structure
#         "notes_md": "..."
#     },
#     "agent_id": "a1b2c3d4-e5f6-...",
#     "messages": [
#         {"role": "user", "content": "Review this codebase..."},
#         {"role": "assistant", "content": "..."},
#         # ... full transcript
#     ],
#     "message_count": 42,
#     "error": null
# }
"""

# Python code (if calling from Python directly, not from agent):
from adgn.mcp.subagents.models import RunSubagentInput, RunSubagentOutput

input_model = RunSubagentInput(
    prompt=render_critic_prompt(specimen),
    mcp_config={
        "mcpServers": {
            "runtime": properties_docker_spec(...),
            "critic_submit": {...}
        }
    },
    timeout_secs=300
)
result: RunSubagentOutput = await client.call_tool(
    "subagents_run_subagent",
    input_model.model_dump()
)
# result.final_result = CriticSubmitPayload dict
# result.agent_id = UUID
# result.status = "complete" | "timeout" | "error"
```

**With subagents (Phase 1b - async)**:
```python
# Agent MCP calls:
"""
spawn_result = subagents.spawn_subagent({
    "prompt": "...",
    "mcp_config": {...}
})
# spawn_result = {
#     "token": "550e8400-e29b-41d4-a716-446655440000",
#     "agent_id": "a1b2c3d4-...",
#     "status": "starting"
# }

# ... do other work ...

result = subagents.await_completion({
    "token": spawn_result["token"],
    "timeout_secs": 300
})
# result = {
#     "status": "complete",
#     "final_result": {"issues": [...]},  # CriticSubmitPayload
#     "message_count": 42,
#     "agent_id": "a1b2c3d4-...",
#     "error": null
# }
"""
```

**Benefits**:
- **70% less boilerplate** (no manual compositor setup, agent creation, stack management)
- **Token-based access** (optimizer can pass critic token to grader for context)
- **Unified error handling** (timeout, resource limits, cleanup all standard)

---

### 2. Grader Runs (Critique Evaluation)

**Current pattern** (`src/adgn/props/grader.py`):
```python
# Ad-hoc: manually build compositor + agent (again!)
async def grade_critique_by_id(critique_id, ...):
    compositor = Compositor("grader")
    # Mount servers: docker exec, grader_submit, resources, ...
    grader_state = GraderSubmitState(...)
    grader_server = make_grader_submit_server(grader_state)
    await compositor.mount_inproc("grader_submit", grader_server)
    # ... (duplicate setup from critic)

    async with Client(compositor) as client:
        agent = await MiniCodex.create(client, handlers=[...])
        result = await agent.run(grader_prompt)

    return grader_state.grade  # GradeSubmitPayload
```

**With subagents (Phase 1a - blocking)**:
```python
# Agent MCP call:
"""
result = subagents.run_subagent({
    "prompt": "Grade this critique...",
    "mcp_config": {"mcpServers": {"grader_submit": {...}}},
    "timeout_secs": 120
})
# result = {
#     "status": "complete",
#     "final_result": {
#         "recall": 0.85,
#         "precision": 0.92,
#         ...  # GradeSubmitPayload structure
#     },
#     "agent_id": "uuid...",
#     "messages": [...],
#     "message_count": 15,
#     "error": null
# }
"""
```

**With subagents (Phase 1b - parallel grading)**:
```python
# Agent MCP calls:
"""
# Spawn multiple graders
tokens = []
for critique_id in critique_ids:
    spawn_result = subagents.spawn_subagent({
        "prompt": f"Grade critique {critique_id}",
        "mcp_config": {"mcpServers": {"grader_submit": {...}}}
    })
    # spawn_result = {"token": "...", "agent_id": "...", "status": "starting"}
    tokens.append(spawn_result["token"])

# Await all
results = subagents.await_many({
    "tokens": tokens,
    "timeout_secs": 120
})
# results = {
#     "results": [
#         {"status": "complete", "final_result": {...}, "message_count": 15, "agent_id": "...", "error": null},
#         {"status": "complete", "final_result": {...}, "message_count": 18, "agent_id": "...", "error": null},
#         ...
#     ]
# }
"""
```

**Benefits**:
- **Reuses infrastructure** (no duplicate compositor setup)
- **Context passing** (grader can reference critic transcript via token)
- **Parallel grading** (spawn multiple graders for different critiques, await all)

---

### 3. Prompt Optimizer (Iterative Improvement)

**Current pattern** (`src/adgn/props/prompt_optimizer.py`):
```python
# Custom orchestrator with ad-hoc critic/grader spawning
async def optimize_prompt(initial_prompt, train_specimens):
    compositor = Compositor("optimizer")
    # Mount prompt_eval server with run_critic/run_grader tools
    # ... which INTERNALLY spawn critics/graders with manual setup

    async with Client(compositor) as client:
        optimizer_agent = await MiniCodex.create(client, ...)
        await optimizer_agent.run("Optimize this prompt for max recall")

    # Problem: optimizer can't access sub-agent transcripts
    # Problem: no unified cost tracking across nested invocations
```

**With subagents (Phase 1a - blocking, simplest)**:
```python
# Optimizer agent MCP calls (synchronous):
"""
# Optimizer has subagents server mounted, runs critics/graders synchronously
# 1. Write prompt candidate via docker_exec.write_file

# 2. Run critic
critic_result = subagents.run_subagent({
    "prompt": "Run critic with prompt from /workspace/prompt-v1.txt on specimen X",
    "mcp_config": {"mcpServers": {"critic_submit": {...}}},
    "timeout_secs": 300
})
# critic_result = {
#     "status": "complete",
#     "final_result": {"issues": [...], "notes_md": "..."},
#     "agent_id": "uuid-critic-1",
#     "messages": [...],
#     "message_count": 42,
#     "error": null
# }

# 3. Run grader
grade_result = subagents.run_subagent({
    "prompt": f"Grade critique {critic_result['agent_id']}",
    "mcp_config": {"mcpServers": {"grader_submit": {...}}},
    "timeout_secs": 120
})
# grade_result = {
#     "status": "complete",
#     "final_result": {"recall": 0.85, "precision": 0.92, ...},
#     "agent_id": "uuid-grader-1",
#     "messages": [...],
#     "message_count": 18,
#     "error": null
# }

# 4. Check recall from grade_result["final_result"]["recall"], iterate
"""
```

**With subagents (Phase 1b - parallel spawn, less efficient)**:
```python
# Agent MCP calls:
"""
# Spawns N fresh agents (repeats context N times - wasteful)
tokens = []
for specimen in ["ducktape/2025-11-20-00", "ducktape/2025-11-21-00", ...]:
    spawn_result = subagents.spawn_subagent({
        "prompt": f"Review {specimen} with prompt: <5000 token prompt>...",  # Context repeated
        "mcp_config": {"mcpServers": {...}}  # MCP config repeated
    })
    # spawn_result = {"token": "uuid...", "agent_id": "uuid...", "status": "starting"}
    tokens.append(spawn_result["token"])

# Await all
results = subagents.await_many({
    "tokens": tokens,
    "timeout_secs": 300
})
# results = {"results": [{"status": "complete", "final_result": {...}, ...}, ...]}
"""
```

**With subagents (Phase 1b - parallel fork, efficient)**:
```python
# Agent MCP calls:
"""
# Agent reaches checkpoint: "I've loaded the prompt candidate, now test on N specimens"
# Fork instead of spawn (inherits full parent transcript + MCP servers)
fork_result = subagents.fork_and_continue({
    "continuations": [
        "Test on specimen ducktape/2025-11-20-00",
        "Test on specimen ducktape/2025-11-21-00",
        "Test on specimen ducktape/2025-11-22-00",
        # ... 7 more (10 total)
    ],
    "timeout_secs": 300
})
# fork_result = {
#     "tokens": ["uuid1", "uuid2", "uuid3", ...],  # 10 tokens
#     "agent_ids": ["tid1", "tid2", "tid3", ...]  # 10 transcript IDs
# }
# Each fork inherits:
# - Parent's full transcript (5000 tokens of context)
# - Parent's MCP servers (critic_submit, docker_exec, etc.)
# - Parent's capabilities/tokens
# Each fork just gets a 10-token continuation message

# Await all forks
results = subagents.await_many({
    "tokens": fork_result["tokens"],
    "timeout_secs": 300
})
# results = {
#     "results": [
#         {"status": "complete", "final_result": {"issues": [...]}, "message_count": 38, "agent_id": "tid1", "error": null},
#         {"status": "complete", "final_result": {"issues": [...]}, "message_count": 42, "agent_id": "tid2", "error": null},
#         {"status": "complete", "final_result": {"issues": [...]}, "message_count": 35, "agent_id": "tid3", "error": null},
#         # ... 7 more (10 total)
#     ]
# }

# Aggregate recalls from results, iterate
"""
```

**Benefits of fork vs. spawn**:
- **70% less token usage**: Context written once (parent), not N times (spawns)
- **Automatic permission transfer**: Forks inherit parent's MCP servers, capabilities, tokens
- **Natural execution model**: "I'm at checkpoint X, now parallelize across N variants"
- **Example savings**: Optimizer testing 10 specimens
  - Spawn: 10 × (5000 token prompt + MCP config) = 50,000 input tokens
  - Fork: 5000 token prompt (once) + 10 × (50 token continuation) = 5,500 input tokens (~90% savings)
```

**Benefits**:
- **Transparent nesting** (optimizer → critics → graders, all tracked)
- **Unified cost accounting** (sum costs across token tree)
- **Transcript access** (optimizer can read critic/grader transcripts to debug failures)
- **Parallel eval** (spawn 10 critics in parallel on train set, await all)

---

## Extended Use Cases (Future)

### 1. MCP Server Delegation

**Scenario**: Parent agent spawns sub-agent and gives it access to the same Docker container.

```python
# Parent agent spawns runtime container
runtime_token = subagents.spawn_mcp_server({
    "type": "runtime",
    "spec": {"image": "adgn-runtime:latest", ...}
})
# runtime_token grants access to exec tool on this container instance

# Parent spawns sub-critic with runtime access
sub_token = subagents.spawn_subagent({
    "prompt": "Analyze dead code using runtime_token={runtime_token}",
    "mcp_servers": [runtime_token]  # Pass token as MCP mount
})

# Sub-critic can now call runtime.exec on parent's container
```

**Implementation**:
- `spawn_mcp_server` returns a token that maps to a `FastMCP` server instance
- `mcp_servers: [token]` in `spawn_subagent` mounts that server in child's compositor
- Cleanup: when parent session ends, both runtime container and sub-agent are torn down

---

### 2. Shared Read-Only Volumes

**Scenario**: Parent creates a volume with utility scripts, shares across multiple sub-agents (DRY).

```python
# Parent creates shared volume
volume_token = subagents.create_shared_volume({
    "path": "/shared-utils",
    "content": {"analyze.py": "...", "report.py": "..."},
    "mode": "ro"  # Read-only
})

# Spawn multiple sub-critics with shared volume
for module in modules:
    subagents.spawn_subagent({
        "prompt": f"Analyze {module} using /shared-utils/analyze.py",
        "volumes": [volume_token]  # Mount as read-only
    })

# All sub-agents see the same utility scripts (no duplication)
```

**Implementation**:
- `create_shared_volume` writes to temp dir, returns token mapping to mount spec
- Token lifecycle: volume persists until parent session ends (or explicit cleanup)
- Future: support caching (content-addressed volumes to avoid re-creating identical payloads)

---

### 3. K8s Scope Tokens (Future)

**Scenario**: Parent has K8s namespace access, delegates read-only pod listing to sub-agent.

```python
# Parent obtains K8s credential token
k8s_token = subagents.create_k8s_scope({
    "namespace": "prod",
    "permissions": ["list_pods", "read_logs"]
})

# Spawn sub-agent with K8s access
subagents.spawn_subagent({
    "prompt": "Check pod health in prod namespace",
    "k8s_scopes": [k8s_token]
})
```

**Implementation**: Deferred (requires K8s MCP server, RBAC integration, credential management).

---

## Implementation Priority

### Immediate Value: Unify Existing Flows

The **highest-priority win** is unifying critic/grader/optimizer invocations under `subagents`:

**Current pain points**:
1. **~100 lines of boilerplate** per critic/grader run (compositor setup, agent creation, state management, cleanup)
2. **No transcript access** (optimizer can't see why critic failed)
3. **No cost tracking** across nested invocations (optimizer → critics → graders)
4. **No parallelism primitives** (spawn 10 critics, await all)
5. **Duplicate infra code** (critic.py, grader.py, prompt_optimizer.py all reimplement agent spawning)

**After `subagents` MVP**:
1. **Single abstraction** for "spawn focused agent, get result"
2. **Token-based access** (pass tokens between optimizer → grader for context)
3. **Automatic cost rollup** (sum costs across token tree)
4. **Built-in parallelism** (`await asyncio.gather(*[await_completion(t) for t in tokens])`)
5. **Delete ~300 lines** of duplicate setup code

**ROI estimate**: ~2 days to implement `subagents` server, ~1 day to refactor critic/grader/optimizer, saves 70% boilerplate on every future eval tool.

---

## Summary

**Core idea**: **Resource capability tokens** as unforgeable references to shared resources (transcripts, MCP servers, volumes, etc.). Spawning/creating gives you a token; holding a token grants access; tokens can be passed freely.

**Benefits**:
- **Isolation by default**: Agents see nothing without tokens
- **Delegation**: Tokens are just data; include in messages to share access
- **Simple**: UUIDs + server-side validation; no complex ACL rules or crypto overhead
- **Composable**: Supports hierarchical spawning, chat, multi-agent collaboration, resource sharing
- **Extensible**: Same token model works for transcripts, MCP servers, volumes, future resources

**MVP scope** (subsumes existing critic/grader/optimizer flows):

**Phase 1a (Blocking/Synchronous - simplest)**:
1. **Single blocking tool**:
   - `run_subagent({prompt, mcp_config, timeout, ...})` → `{final_result, agent_id, messages}`
   - Spawns agent, waits for completion, returns result (all in one call)
   - Perfect drop-in replacement for current `run_critic`/`grade_critique_by_id` patterns
2. **No token management** (yet) - just spawn-and-block
3. **Unified agent spawning** (replaces ad-hoc patterns):
   - Critic invocations (currently `run_critic` → manual compositor + agent setup)
   - Grader invocations (currently `grade_critique_by_id` → manual compositor + agent setup)

**Phase 1b (Async/Token-based - eventual)**:
1. **Split operations**:
   - `spawn_subagent({prompt, ...})` → `{token}` (non-blocking, returns immediately)
   - `await_completion(token, timeout)` → `{final_result, ...}` (blocks until done)
2. **Fork at checkpoint** (efficient parallelization):
   - `fork_and_continue({continuations: [msg1, msg2, ...]})` → `{tokens: [t1, t2, ...]}`
   - Each fork inherits parent's full transcript + MCP servers + capabilities
   - Each fork gets a different continuation message appended
   - Parent can `await_many(tokens)` to block until all complete
3. **Optional tools** (for advanced patterns):
   - `read_transcript(token)` → `{messages, is_complete}`
   - `send_message(token, message)` → `{status}` (for chat/follow-ups)
4. **Enables**:
   - Efficient parallel execution (fork N times with shared context, not N fresh spawns)
   - Prompt optimizer: "fork me for each specimen" vs. "spawn N critics with repeated context"
   - Chat use case (bidirectional communication)
5. **Cascading cleanup** (parent disconnect tears down children)

**Phase 2 (MCP server delegation)**:
1. `spawn_mcp_server` / `attach_mcp_server` (returns server token)
2. `mcp_servers: [token]` in `spawn_subagent` (mount by token reference)
3. **Unifies runtime container sharing** (e.g., parent/child both exec in same Docker container)

**Phase 3 (shared volumes)**:
1. `create_shared_volume` (returns volume token)
2. `volumes: [token]` in `spawn_subagent` (mount by token reference)
3. **DRY utility scripts** across sub-agent invocations

---

## Implementation Order

### Principles

1. **Quick wins first**: Deliver value early (unify critic/grader flows)
2. **Risk reduction**: Test core assumptions before building more
3. **Incremental delivery**: Each milestone is independently useful
4. **Dependencies**: Build foundation → features → optimizations

---

### Milestone 1: Foundation (Day 1 morning, ~2 hours)

**Goal**: Basic infrastructure + DB schema ready

**Deliverables**:
1. **Capability registry** (in-memory)
   - `dict[str, Capability]` mapping token → resource
   - `Capability` dataclass with `token`, `resource_type`, `resource_id`, `granted_by`
   - Token generation (UUID4)
   - Token validation helper

2. **Subagents MCP server scaffolding**
   - `src/adgn/mcp/subagents/server.py` (FastMCP server)
   - `src/adgn/mcp/subagents/models.py` (Pydantic I/O models)
   - Register server in standard mounts (like `compositor_admin`)

3. **Smoke test**
   - Server starts, can be mounted, tools list correctly

**Success criteria**:
- [ ] `make_subagents_server()` returns FastMCP instance
- [ ] Server has `run_subagent` tool stub (raises NotImplementedError)

---

### Milestone 2: Postgres RLS Setup (Day 1 afternoon, ~4 hours)

**Goal**: Database access control in place BEFORE building agent spawning

**Why now**: Agents will have DB credentials from the start; no need to build throwaway MCP query tools

**Deliverables**:
1. **Schema changes (ALTER TABLE directly in prod)**
   - Rename `transcript_id` → `agent_id` in `critic_runs`, `grader_runs`, `prompt_optimization_runs`, `events`
   - Add `agent_grants` table: `(grantor_agent_id UUID, grantee_agent_id UUID, granted_at TIMESTAMP)`
   - Add `parent_agent_id` column to `critic_runs`, `grader_runs` (nullable, for hierarchy tracking)
   - Add indexes: `idx_agent_grants_grantee`, `idx_critic_runs_parent`, `idx_grader_runs_parent`

   ```sql
   -- Rename columns
   ALTER TABLE critic_runs RENAME COLUMN transcript_id TO agent_id;
   ALTER TABLE grader_runs RENAME COLUMN transcript_id TO agent_id;
   ALTER TABLE prompt_optimization_runs RENAME COLUMN transcript_id TO agent_id;
   ALTER TABLE events RENAME COLUMN transcript_id TO agent_id;

   -- Add parent tracking
   ALTER TABLE critic_runs ADD COLUMN parent_agent_id UUID;
   ALTER TABLE grader_runs ADD COLUMN parent_agent_id UUID;
   CREATE INDEX idx_critic_runs_parent ON critic_runs(parent_agent_id);
   CREATE INDEX idx_grader_runs_parent ON grader_runs(parent_agent_id);

   -- Create agent_grants table
   CREATE TABLE agent_grants (
       grantor_agent_id UUID NOT NULL,
       grantee_agent_id UUID NOT NULL,
       granted_at TIMESTAMP NOT NULL DEFAULT NOW(),
       PRIMARY KEY (grantor_agent_id, grantee_agent_id)
   );
   CREATE INDEX idx_agent_grants_grantee ON agent_grants(grantee_agent_id);
   ```

1b. **SQLAlchemy model updates (DRY via mixin)**
   ```python
   # src/adgn/props/db/models.py

   class AgentMixin:
       """Mixin for tables that represent agent runs."""
       agent_id: Mapped[UUID] = mapped_column(
           PG_UUID(as_uuid=True),
           nullable=False,
           index=True,
           comment="Unique agent ID (formerly transcript_id)"
       )
       parent_agent_id: Mapped[UUID | None] = mapped_column(
           PG_UUID(as_uuid=True),
           nullable=True,
           index=True,
           comment="Parent agent ID (for hierarchy tracking)"
       )

   class CriticRun(Base, AgentMixin):
       __tablename__ = "critic_runs"
       id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
       # agent_id, parent_agent_id inherited from AgentMixin
       prompt_sha256: Mapped[str] = ...
       # ... rest of fields

   class GraderRun(Base, AgentMixin):
       __tablename__ = "grader_runs"
       id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
       # agent_id, parent_agent_id inherited from AgentMixin
       critique_id: Mapped[UUID] = ...
       # ... rest of fields

   class PromptOptimizationRun(Base, AgentMixin):
       __tablename__ = "prompt_optimization_runs"
       id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
       # agent_id, parent_agent_id inherited from AgentMixin
       budget_limit: Mapped[float] = ...
       # ... rest of fields

   class Event(Base):
       __tablename__ = "events"
       id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
       agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)  # Renamed from transcript_id
       # ... rest of fields

   class AgentGrants(Base):
       __tablename__ = "agent_grants"
       grantor_agent_id: Mapped[UUID] = mapped_column(
           PG_UUID(as_uuid=True),
           primary_key=True,
           comment="Agent granting access"
       )
       grantee_agent_id: Mapped[UUID] = mapped_column(
           PG_UUID(as_uuid=True),
           primary_key=True,
           comment="Agent receiving access"
       )
       granted_at: Mapped[datetime] = mapped_column(
           TIMESTAMP,
           nullable=False,
           server_default=func.now()
       )
   ```

2. **RLS policies**
   - Enable RLS on `critic_runs`, `grader_runs`, `critiques`, `specimens`, `prompts`
   - Policy pattern (example for `critic_runs`):
     ```sql
     CREATE POLICY agent_isolation ON critic_runs FOR SELECT USING (
       -- My own runs
       agent_id::text = replace(current_user, 'agent_', '')
       OR
       -- Granted runs
       agent_id::text IN (
         SELECT replace(grantor_agent_id::text, '-', '')
         FROM agent_grants
         WHERE replace(grantee_agent_id::text, '-', '') = replace(current_user, 'agent_', '')
       )
     );
     ```

3. **Role creation helper**
   - `async def create_agent_role(agent_id: UUID) -> (username: str, password: str)`
   - Creates `agent_{uuid_hex}` role with LOGIN, generated password
   - Grants SELECT, INSERT, UPDATE on relevant tables
   - Returns credentials for container env vars

4. **Role cleanup helper**
   - `async def drop_agent_role(agent_id: UUID)`
   - Terminates active connections, drops role

**Success criteria**:
- [ ] Schema changes applied (columns renamed, tables created, indexes added)
- [ ] SQLAlchemy models updated (AgentMixin added, models inherit from it)
- [ ] Unit test: `create_agent_role` → role exists, has table permissions
- [ ] Unit test: RLS policy blocks cross-agent reads (agent A cannot see agent B's data)
- [ ] Unit test: RLS policy allows granted reads (after inserting grant, agent A sees agent B's data)

**Foundation established**: All subsequent agent spawning gets DB credentials automatically

---

### Milestone 3: `run_subagent` MVP (Day 2, ~6 hours)

**Goal**: `run_subagent` works end-to-end with DB credentials baked in

**Deliverables**:
1. **Agent spawning with DB credentials**
   - Generate `agent_id` (UUID)
   - Call `create_agent_role(agent_id)` → get username, password
   - Create Compositor from `mcp_config` param
   - Inject DB credentials into container env: `PGUSER`, `PGPASSWORD`, `PGHOST`, `PGDATABASE`
   - Create MiniCodex agent with handlers
   - Run agent with prompt

2. **Parent-child grant creation**
   - If spawned by another agent (has `parent_agent_id`):
     - Insert into `agent_grants`: `(grantor=child, grantee=parent, granted_at=NOW())`
     - Parent can now see child's DB records (via RLS)

3. **Final result extraction**
   - Heuristic: Use result from last tool call (if structured content exists)
   - Fallback: Return `null` if no structured output

4. **Lifecycle management**
   - Timeout enforcement (via asyncio.wait_for)
   - Error handling (agent failure → status="error", error message)
   - Cleanup: close compositor, drop agent role

5. **`run_subagent` implementation**
   - Input: `RunSubagentInput` (prompt, mcp_config, timeout_secs, model, parent_agent_id?)
   - Output: `RunSubagentOutput` (status, final_result, agent_id, messages, message_count, error)

**Success criteria**:
- [ ] E2E test: `run_subagent` → agent can query DB via `psql` (RLS filters results)
- [ ] E2E test: Parent spawns child → parent queries DB, sees child's data (via grant)
- [ ] E2E test: `run_subagent` with timeout → status="timeout", role cleaned up
- [ ] Unit test: DB credentials injected correctly into container env

**Risk reduction**: Proves DB access + RLS work before refactoring critic/grader

---

### Milestone 4: Critic/Grader Integration (Day 2-3, ~6 hours)

**Goal**: Replace ad-hoc spawning in `run_critic`/`grade_critique_by_id` with `run_subagent`

**Deliverables**:
1. **Refactor `run_critic`**
   - Remove manual Compositor/MiniCodex setup (~50 lines)
   - Call `run_subagent` with critic prompt + critic_submit server
   - Extract `CriticSubmitPayload` from `final_result`
   - Preserve DB writes (critic_runs table with agent_id + parent_agent_id)
   - Critics automatically get DB credentials (can query specimens, prompts, etc.)

2. **Refactor `grade_critique_by_id`**
   - Remove manual Compositor/MiniCodex setup (~50 lines)
   - Call `run_subagent` with grader prompt + grader_submit server
   - Extract `GradeSubmitPayload` from `final_result`
   - Preserve DB writes (grader_runs table with agent_id + parent_agent_id)
   - Graders automatically get DB credentials (can query critique, ground truth, etc.)

3. **Update prompt_optimizer**
   - Use refactored `run_critic`/`grade_critique_by_id` (automatically get `run_subagent` benefits)
   - Optimizer can query DB to see all critic/grader runs it spawned (via RLS grants)

**Success criteria**:
- [ ] Existing critic E2E tests pass (no behavior change)
- [ ] Existing grader E2E tests pass (no behavior change)
- [ ] LOC reduction: ~100 lines deleted across critic.py, grader.py
- [ ] DB writes preserved (critic_runs, grader_runs, critiques tables)
- [ ] DB access works: critic can query `specimens`, grader can query `critiques`

**Quick win**: Immediate value (less boilerplate + DB access), proves design works with real use cases

**🚩 CHECKPOINT**: Ship this! MVP is done, rest is optimization.

---

### Milestone 5: Async Primitives (Day 3-4, ~6 hours)

**Goal**: `spawn_subagent` + `await_completion` working (foundation for parallelism)

**Deliverables**:
1. **Agent lifecycle tracking**
   - `dict[str, AgentHandle]` mapping token → running agent
   - `AgentHandle` with agent, task, status, agent_id, result

2. **`spawn_subagent` implementation**
   - Start agent in background (asyncio.create_task)
   - Generate token, store in registry
   - Return token + agent_id immediately
   - Agent continues running asynchronously

3. **`await_completion` implementation**
   - Validate token
   - Wait for agent task to complete (with timeout)
   - Extract final result, transcript
   - Return completion status

4. **`get_status` implementation**
   - Validate token
   - Return current status (running/complete/error) without blocking

**Success criteria**:
- [ ] E2E test: spawn → status (running) → await → status (complete)
- [ ] E2E test: spawn 3 → await all → get 3 results
- [ ] Unit test: Token validation (invalid token → ToolError)
- [ ] Unit test: Timeout handling (await with short timeout → timeout error)

**Foundation**: Enables all parallelism patterns (optimizer, batch grading)

---

### Milestone 6: Batch Operations (Day 4, ~4 hours)

**Goal**: `await_many` for efficient parallel waits

**Deliverables**:
1. **`await_many` implementation**
   - Input: list of tokens
   - Wait for all agents concurrently (asyncio.gather)
   - Return list of results (same order as input tokens)
   - Handle partial failures (some complete, some timeout)

2. **Refactor prompt optimizer** (optional, if time permits)
   - Use `spawn_subagent` + `await_many` for parallel critic runs
   - Measure wall-clock time improvement (sequential → parallel)

**Success criteria**:
- [ ] E2E test: spawn 5 critics → await_many → get 5 results
- [ ] E2E test: Mixed success/failure (3 complete, 2 timeout) → all captured
- [ ] Performance test: 10 critics in parallel < 2× single critic time

**Value**: Unblocks prompt optimizer parallelization (big win for eval speed)

---

### Milestone 7: Fork Optimization (Day 5, ~8 hours)

**Goal**: `fork_and_continue` for efficient context sharing

**Deliverables**:
1. **Fork implementation**
   - Clone parent transcript (messages list)
   - Clone parent MCP servers (share compositor mounts)
   - Clone parent capabilities (token inheritance)
   - Append continuation message to each fork
   - Spawn N agents in parallel

2. **`fork_and_continue` implementation**
   - Input: list of continuation messages
   - Create N forks with inherited state
   - Return N tokens
   - Each fork runs independently

3. **Capability inheritance**
   - When forking, copy parent's token grants to children
   - Children can access parent's MCP servers (no re-mount)

**Success criteria**:
- [ ] E2E test: fork 3 with different continuations → 3 different results
- [ ] E2E test: Forks inherit parent transcript (verify messages present)
- [ ] E2E test: Forks inherit parent MCP servers (verify tool access)
- [ ] Token savings test: Fork 10 critics vs. spawn 10 critics (90% reduction)

**Big win**: Massive token savings for prompt optimizer (50K → 5.5K tokens)

**🚩 CHECKPOINT**: Major value delivered (parallelism + token savings)

---

### Milestone 8: MCP Server Delegation (Day 6-7, ~8 hours)

**Goal**: Share MCP server handles between parent/child agents

**Deliverables**:
1. **Token model extension**
   - Add `resource_type="mcp_server"` capability
   - Map token → MCP server name/handle in parent's compositor

2. **`spawn_mcp_server` tool**
   - Input: MCP server spec (e.g., Docker runtime config)
   - Spawn server, generate token
   - Return token (grants access to server's tools)

3. **`attach_mcp_server` tool**
   - Input: token (from parent)
   - Mount server in child's compositor (by reference, not re-create)
   - Child can now call tools on parent's server

4. **Mount by token in `spawn_subagent`**
   - Add `mcp_tokens: list[str]` param to `SpawnSubagentInput`
   - On spawn: Resolve tokens → mount servers in child compositor

**Success criteria**:
- [ ] E2E test: Parent spawns Docker runtime → child uses same container
- [ ] E2E test: Parent spawns seatbelt server → child executes commands
- [ ] Unit test: Token validation (invalid MCP token → ToolError)

**Value**: Efficient resource sharing (1 Docker container for parent + N children)

---

### Milestone 9: Shared Volumes (Day 7-8, ~4 hours)

**Goal**: DRY utility scripts across subagent invocations

**Deliverables**:
1. **`create_shared_volume` tool**
   - Input: path, content dict (filename → content), mode (ro/rw)
   - Create temp dir, write files, generate token
   - Return token

2. **Mount by token**
   - Add `volume_tokens: list[str]` param to `SpawnSubagentInput`
   - On spawn: Resolve tokens → mount volumes in child container

3. **Lifecycle management**
   - Cleanup: Delete temp dir when parent session ends
   - Cache: Content-addressed volumes (same content → same dir, reuse)

**Success criteria**:
- [ ] E2E test: Parent creates volume → spawn 3 children → all see same files
- [ ] E2E test: Parent disconnects → volume cleaned up
- [ ] Unit test: Content-addressed caching (same content → same dir)

**Value**: Reduces duplication (utility scripts written once, mounted N times)

---

## Summary Timeline

| Milestone | Duration | Cumulative | Deliverable |
|-----------|----------|------------|-------------|
| 1. Foundation | 2h | Day 1 AM | Infrastructure + server scaffolding |
| 2. Postgres RLS Setup | 4h | Day 1 PM | **Database schema + RLS policies** |
| 3. `run_subagent` MVP | 6h | Day 2 | Blocking tool with DB credentials baked in |
| 4. Critic/Grader Integration | 6h | Day 2-3 | **Refactor existing flows (quick win) ← SHIP THIS** |
| 5. Async Primitives | 6h | Day 3-4 | `spawn`/`await` foundation |
| 6. Batch Operations | 4h | Day 4 | `await_many` for parallelism |
| 7. Fork Optimization | 8h | Day 5 | **`fork_and_continue` (token savings) ← MAJOR VALUE** |
| 8. MCP Delegation | 8h | Day 6-7 | Share MCP servers via tokens |
| 9. Shared Volumes | 4h | Day 7-8 | DRY utility scripts |

**Total**: ~7-8 days (assuming 6 hour workdays, 48 hours total)

**Critical path**:
1. Foundation → RLS → `run_subagent` → Critic/Grader (Days 1-3) — **Must happen first** (proves design + security)
2. Async → Batch → Fork (Days 3-5) — **High value** (parallelism + token savings)
3. MCP → Volumes (Days 6-8) — **Nice-to-have** (resource sharing optimizations)

**Suggested checkpoints**:
- **After Milestone 4** (Day 2-3): Ship it! (MVP with security baked in, rest is optimization)
- **After Milestone 7** (Day 5): Major value delivered (parallelism + token savings)

---

## Risk Mitigation

### High-risk items (test early)
1. **Final result extraction** (Milestone 3): How to reliably get structured output from submit servers?
   - Mitigation: Prototype in Milestone 3, iterate if needed
2. **MCP server cloning** (Milestone 8): Can we safely share compositor mounts between agents?
   - Mitigation: Spike in Milestone 5 (when building spawn_subagent)
3. **Role lifecycle** (Milestone 2): When to DROP roles? Need clear termination signal
   - Mitigation: Start with explicit cleanup only (no automatic sweeping), revisit if orphans accumulate

### Dependencies
- Milestone 3 depends on Milestone 2 (`run_subagent` needs RLS setup first)
- Milestones 5-7 depend on Milestone 3 (`run_subagent` must work first)
- Milestones 8-9 depend on Milestone 5 (need token model working for async operations)

### Cut scope if needed
- **Low priority**: Milestones 8-9 (MCP delegation, shared volumes) — can defer
- **Medium priority**: Milestones 5-7 (async, batch, fork) — ship Milestone 4 first, add parallelism later
- **High priority**: Milestones 1-4 — these are the core value proposition (foundation + security + MVP + integration)

---

## Implementation Notes

- Each milestone is independently testable and deployable
- Focus on E2E tests (agent spawning is complex, unit tests only catch so much)
- Measure LOC reduction after Milestone 3 (quantify value)
- Measure token savings after Milestone 6 (quantify optimization)
- Consider pausing after Milestone 3 to gather feedback before building more
