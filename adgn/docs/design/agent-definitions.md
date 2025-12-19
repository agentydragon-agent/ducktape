# Agent Definitions

## Overview

Agent definitions are self-contained directories that fully specify an agent's behavior:
prompt, bootstrap logic, and supporting tools/scripts. They are stored in PostgreSQL
as compressed archives with content-addressed identity and database-level access control.

## Goals

1. **Evolvable agents**: The prompt optimizer can modify not just prompts, but the entire
   agent definition including helper scripts and tooling
2. **Uniform format**: All agent types (critic, grader, optimizer) use the same structure
3. **Single source of truth**: Definitions stored in PostgreSQL, inflated to workspace on demand
4. **Access control**: Database RLS controls which definitions an agent can read/write

## Provenance Model

**All provenance tracking uses `transcript_id`** - the unique identifier for a specific
agent run. This replaces:
- Separate `critic_runs`, `grader_runs`, `prompt_optimization_runs` tables → unified `agent_runs`
- Separate `prompt_optimization_run_id`, `improvement_run_id` columns → `created_by_transcript_id`

Benefits:
- Single consistent pattern across all tables
- Direct link to full agent transcript for debugging
- **One `agent_runs` table** instead of per-agent-type tables
- Simpler RLS policies (just check `current_transcript_id()`)
- Lineage via `parent_transcript_id` in `agent_runs`

Tables using `created_by_transcript_id` for provenance:
- `agent_definitions` - which agent created this definition
- `prompts` - which agent created this prompt (replaces `prompt_optimization_run_id`, `improvement_run_id`)
- Any other artifact table

For repo-backed/manual entries, `created_by_transcript_id` is NULL.

## Directory Structure

Minimal conventions:

```
<agent_definition>/
├── AGENT.md              # System prompt (required)
├── init               # Runs on agent startup (required, must be executable)
└── ...                   # Any other files the agent needs
```

### AGENT.md

The complete system prompt. This is what the agent "is". Fully self-contained.

Example structure:
```markdown
You are a code quality critic agent. Your job is to review code and identify issues.

## Your Task
Review the snapshot code and report issues using the available tools.

## Getting Started
Run `./init` for environment details and available tools.
(Note: Runtime auto-executes this, but instruction remains for clarity)

## Workflow
1. Analyze code using available tools (rg, ruff, mypy, etc.)
2. Report issues using Python helpers or direct SQL
3. Complete review by calling submit_critique()

... (rest of agent-specific instructions)
```

### init

Required, must be executable. Executed automatically by the runtime before agent
sampling begins (warm-start pattern - we don't rely on LLM following an instruction).

Default init for repo-tracked agents is written in Python and reads common
boilerplate from the installed adgn package:

```python
#!/usr/bin/env python3
"""Init script for critic agent."""

import os
from importlib.resources import files

# Read MCP connection info from adgn package resources
print(files('adgn.props.prompts').joinpath('mcp_http_connection.md').read_text())

# Read scope from environment (set by runtime)
print("=== Review Scope ===")
print(f"Snapshot: {os.environ.get('SNAPSHOT_SLUG', 'N/A')}")
print(f"Files: {os.environ.get('SCOPE_FILES', 'N/A')}")

# Any agent-specific setup...
```

Exit non-zero to abort agent startup.

### Other files

No restrictions. Common patterns:
- `tools/` - executable scripts the agent can invoke
- `context/` - reference documentation
- `examples/` - worked examples for few-shot guidance

## Storage

### Unified Agent Runs Table

Instead of separate `critic_runs`, `grader_runs`, `prompt_optimization_runs` tables,
use a single unified table with agent-type-specific columns and CHECK constraints:

```sql
CREATE TABLE agent_runs (
    transcript_id UUID PRIMARY KEY,
    agent_type TEXT NOT NULL,                    -- 'critic', 'grader', 'prompt_optimizer'
    agent_definition_id TEXT REFERENCES agent_definitions(id),
    status TEXT NOT NULL DEFAULT 'running',
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Provenance: which agent spawned this one?
    parent_transcript_id UUID REFERENCES agent_runs(transcript_id),

    -- Common columns
    model TEXT NOT NULL,

    -- Critic-specific (NULL for other agent types)
    snapshot_slug TEXT,
    scope_hash TEXT,

    -- Grader-specific (NULL for other agent types)
    graded_transcript_id UUID REFERENCES agent_runs(transcript_id),

    -- Output (JSONB, structure depends on agent_type)
    output JSONB,

    -- CHECK constraints for column presence by agent_type
    CONSTRAINT critic_columns CHECK (
        agent_type != 'critic' OR (snapshot_slug IS NOT NULL AND scope_hash IS NOT NULL)
    ),
    CONSTRAINT grader_columns CHECK (
        agent_type != 'grader' OR graded_transcript_id IS NOT NULL
    )
);

CREATE INDEX idx_agent_runs_type ON agent_runs(agent_type);
CREATE INDEX idx_agent_runs_parent ON agent_runs(parent_transcript_id);
CREATE INDEX idx_agent_runs_snapshot ON agent_runs(snapshot_slug) WHERE snapshot_slug IS NOT NULL;
```

Benefits:
- **transcript_id is THE universal identifier** for any agent run
- Lineage via `parent_transcript_id` - trivial to trace "who spawned who"
- Single RLS policy set
- Easy cross-agent queries
- Type-specific columns with CHECK constraints ensure data integrity

The `events` table already uses `transcript_id` as FK, so tool calls link naturally.

### Agent Definitions Schema

```sql
CREATE TABLE agent_definitions (
    id TEXT PRIMARY KEY,                   -- readable: 'critic', 'grader', or auto-generated
    agent_type TEXT NOT NULL,              -- 'critic', 'grader', 'prompt_optimizer', etc.
    archive BYTEA NOT NULL,                -- uncompressed tar archive
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Provenance (set when created by an agent, NULL for repo-backed)
    created_by_transcript_id UUID          -- transcript of agent that created this definition
);

-- Index for finding definitions by type
CREATE INDEX idx_agent_definitions_type ON agent_definitions(agent_type);
```

ID conventions:
- Repo-backed: readable names like `"critic"`, `"grader"`, `"prompt_optimizer"`
- Agent-created: auto-generated (e.g., `"critic_a1b2c3"` or UUID)

Agents can INSERT directly into this table (with RLS ensuring they can only insert
rows where `created_by_transcript_id` matches their transcript). No UPDATE allowed.

### Content Hashing (Optional)

For deduplication or integrity checks, compute SHA256 of the definition:

```python
def compute_definition_hash(definition_dir: Path) -> str:
    """Compute SHA256 of agent definition directory."""
    hasher = hashlib.sha256()
    for path in sorted(definition_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(definition_dir)
            mode = "x" if os.access(path, os.X_OK) else "r"
            hasher.update(f"{rel}:{mode}:".encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()
```

This can be used to generate auto-IDs (e.g., `"critic_" + sha[:8]`) or for
detecting duplicate submissions.

## Access Control

### RLS Policies

```sql
-- All agents can read all definitions (no secrets in agent definitions)
CREATE POLICY read_all ON agent_definitions
    FOR SELECT
    USING (true);

-- Agents can only INSERT with their own transcript_id
CREATE POLICY insert_own ON agent_definitions
    FOR INSERT
    WITH CHECK (created_by_transcript_id = current_transcript_id());

-- No UPDATE or DELETE allowed
```

Repo-backed definitions have `created_by_transcript_id = NULL` and are inserted
by the sync command (not by agents).

### Transcript Access

Each agent can always read its own transcript (events table):

```sql
-- Agent can read events from its own transcript
CREATE POLICY read_own_transcript ON events
    FOR SELECT
    USING (transcript_id = current_transcript_id());
```

This allows agents to reflect on their own history if needed.

## Agent Access Pattern

Agents do NOT get definitions auto-mounted. Instead, they use a helper to inflate
definitions from the database into their workspace:

### Python Helper

```python
from adgn.props.agent_helpers import inflate_agent_definition

# Inflate a specific definition by ID
inflate_agent_definition(definition_id="critic_a1b2c3", target_dir=Path("/workspace/agents/critic_a1b2c3"))

# Inflate the baseline critic definition
inflate_agent_definition(definition_id="critic", target_dir=Path("/workspace/agents/critic"))

# Inflate own definition (uses environment variable set by runtime)
inflate_agent_definition(self=True, target_dir=Path("/workspace/agents/self"))
```

### CLI

```bash
# Inflate by ID
inflate-agent critic_a1b2c3 /workspace/agents/critic_a1b2c3

# Inflate baseline (just use the readable ID)
inflate-agent critic /workspace/agents/critic

# Inflate self
inflate-agent --self /workspace/agents/self
```

### Bootstrap Integration (Warm-Start)

The agent runtime automatically:
1. Unpacks agent definition to `/workspace`
2. Sets environment variables (`AGENT_DEFINITION_ID`, `SNAPSHOT_SLUG`, `MCP_SERVER_URL`, etc.)
3. Executes `init` via docker_exec
4. Injects init output as first assistant message (warm-start)
5. Reads `/workspace/AGENT.md` as system prompt
6. Begins agent sampling

This warm-start pattern ensures the agent sees init output without relying
on the LLM to follow an instruction to run it.

Agents that need to read other definitions (e.g., optimizer reading critic) use
the helper explicitly.

## Workflow: Prompt Optimizer Evolving Critic

```
1. Optimizer starts with access to:
   - Its own definition unpacked at /workspace
   - All agent definitions readable via database

2. Optimizer inflates current best critic:
   $ inflate-agent critic /workspace/agents/critic

3. Optimizer reads and analyzes:
   - /workspace/agents/critic/AGENT.md
   - /workspace/agents/critic/tools/...

4. Optimizer creates modified version:
   $ cp -r /workspace/agents/critic /workspace/agents/critic_new
   $ edit /workspace/agents/critic_new/AGENT.md
   $ edit /workspace/agents/critic_new/tools/analyze.py

5. Optimizer saves new definition (INSERT via RLS):
   $ save-agent-definition --type critic /workspace/agents/critic_new
   # Returns: Created agent definition ID critic_a1b2c3

6. Optimizer runs critic with new definition:
   $ run-critic --definition critic_a1b2c3 --snapshot ducktape/2025-01-15
```

## Migration Path

### Phase 1: Schema + Helpers
- Add `agent_definitions` table
- Implement `inflate_agent_definition` and `save_agent_definition` helpers
- Add CLI wrappers

### Phase 2: Migrate Critic
- Convert `critic/prompts/critic_system.j2.md` to `AGENT.md` format
- Create baseline critic definition in database
- Update `CriticAgentEnvironment` to use definition-based setup

### Phase 3: Migrate Other Agents
- Grader
- Prompt optimizer

### Phase 4: Enable Evolution
- Wire up optimizer to create new critic definitions
- Metrics queries that group by definition

## Runtime Information (No Jinja2)

Agent definitions are fully static - no Jinja2 templating.

### How dynamic info is provided

1. **Common boilerplate** (MCP connection docs, tool usage patterns):
   - Stored in `adgn.props.prompts` package resources
   - init reads via `importlib.resources`
   - Shared across all agents, versioned with the adgn package

2. **Run-specific context** (snapshot slug, file scope, credentials):
   - Passed via environment variables (`$SNAPSHOT_SLUG`, `$SCOPE_FILES`, `$PGHOST`, etc.)
   - init prints these for the agent to see

3. **MCP server URL/token**:
   - `$MCP_SERVER_URL` and `$MCP_SERVER_TOKEN` set by runtime
   - init demonstrates connection (already the pattern today)

This keeps AGENT.md fully self-contained while allowing runtime-specific context.

### init output limits

The init output is injected into the conversation as the first assistant
turn (warm-start). To prevent truncation:

- docker_exec tool has `max_output_bytes` parameter:
  - Hard cap: 100KB (server-enforced maximum)
  - Default: 10KB if not specified
  - For OpenAI strict mode: parameter must be explicitly set in schema (even if to null)
- Default init calls set higher limits (e.g., 50KB) explicitly
- E2E tests verify init output is not truncated (see TODO section)

## Syncing Repo-Tracked Definitions

Canonical agent definitions live in git at `adgn/agent_definitions/`. Synced to
database as part of the existing DB sync command:

```bash
# Existing sync command handles agent definitions too
python -m adgn.props.cli db sync

# This (among other things):
# 1. Walks adgn/agent_definitions/
# 2. For each directory, computes SHA256
# 3. Upserts to database if not present (idempotent)
```

The sync runs:
- On CI after merge to main
- Manually when developing new base definitions
- As part of normal DB sync workflow

## Size Limits

- **Folder size**: Soft limit ~1MB (enforced by CLI tooling)
- **Database column**: 2MB limit on `archive` column (hard limit)

## Validation

Validation happens at insert time. A valid agent definition must have:
- `AGENT.md` file (required)
- `init` file that is executable (required)

Insert fails if these requirements are not met.

## Archive Format

Uncompressed tar (let PostgreSQL handle compression via TOAST if beneficial):

```python
def pack_definition(definition_dir: Path) -> bytes:
    """Create tar archive from definition directory."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        for path in definition_dir.rglob("*"):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(definition_dir))
    return buffer.getvalue()

def unpack_definition(archive: bytes, target_dir: Path) -> None:
    """Extract tar archive to target directory."""
    buffer = io.BytesIO(archive)
    with tarfile.open(fileobj=buffer, mode='r') as tar:
        tar.extractall(target_dir)
```

## Self Definition Location

The agent's own definition is unpacked to `/workspace` (the default cwd):

```
/workspace/
├── AGENT.md              # System prompt (complete, self-contained)
├── init               # Auto-executed on startup
└── tools/                # Agent's helper scripts (if any)
```

Agent reads its prompt from `/workspace/AGENT.md`. Simple, no symlinks needed.
Runtime context comes via environment variables, not files.

## TODO

- [ ] E2E test verifying init output is not truncated (check for TruncatedOutput model in
  first step of steps-driven OpenAI mock)

## Future: Sub-Agent Spawning

Agents can spawn sub-agents for task decomposition. A critic might say "go trace the
architecture" or "look for type errors" and delegate to specialized sub-agents.

### Workflow

1. Parent agent creates ad-hoc agent definition:
   ```python
   # Create minimal definition with just AGENT.md
   save_agent_definition(
       agent_type="freeform",  # or "subagent"
       content={"AGENT.md": "You are a code tracer. Analyze how data flows from X to Y..."},
   )
   # Returns: definition_id = "freeform_abc123"
   ```

2. Parent spawns sub-agent via MCP tool:
   ```python
   result = spawn_subagent(
       definition_id="freeform_abc123",
       inherit_mounts=True,  # same snapshot, same /workspace access
       # parent_transcript_id automatically set to current_transcript_id()
   )
   # Blocks until sub-agent completes, returns output
   ```

3. Sub-agent runs with:
   - Its own transcript_id
   - `parent_transcript_id` pointing to parent
   - Same environment (snapshot mounts, DB access)
   - Its ad-hoc AGENT.md as system prompt

4. Parent receives result and continues

### Schema Support

Already handled by unified `agent_runs` table:
- `agent_type = 'freeform'` for ad-hoc sub-agents
- `parent_transcript_id` links to spawning agent
- `agent_definition_id` references the ad-hoc definition

### MCP Tools (Conversational Interface)

Rather than one-shot spawning, sub-agents support continuous conversation:

```python
@mcp.tool()
async def start_agent(
    definition_id: str,
    inherit_mounts: bool = True,
) -> str:
    """Start a sub-agent session.

    Creates a new agent with its own transcript_id, sets up container and
    environment, but does NOT run any turns yet.

    Returns: transcript_id (use with send_message)
    """

@mcp.tool()
async def send_message(
    transcript_id: str,
    message: str,
) -> str:
    """Send a message to a sub-agent.

    Adds the message to the conversation, then runs the agent until it
    produces a text response. Aborts and returns when agent sends text.

    If the container was previously killed (e.g., parent was idle), it will
    be restarted and the agent receives a system message:
    "Your container was restarted. Any local state (files in /tmp, running
    processes, environment variables set at runtime) has been lost. The
    conversation history and mounted volumes are preserved."

    Returns: The agent's text response

    Errors:
    - If agent is already rolling out (concurrent send_message not allowed)
    - If transcript doesn't exist
    """
```

**Workflow:**
```python
# Start a sub-agent for architecture analysis
transcript_id = start_agent(definition_id="freeform_abc123")

# Have a conversation
response1 = send_message(transcript_id, "Trace how API requests reach the database")
# Agent runs, explores code, responds with findings

response2 = send_message(transcript_id, "Now focus on the authentication middleware")
# Continues same conversation, agent has context from previous turns

# ... time passes, container gets cleaned up ...

response3 = send_message(transcript_id, "Summarize your findings")
# Container restarted, agent gets system message about restart, then continues
```

**State Management:**
- Session identified by transcript_id (no separate session concept)
- Conversation history persisted in events table
- No explicit end_agent needed - resources cleaned up when parent exits

### Implementation: Agent Registry

General agent lifecycle management - used by prompt optimizer running critics,
agents spawning sub-agents, CLI, etc. Not sub-agent specific.

```python
class AgentRegistry:
    """Manages long-running agent containers."""

    def __init__(self):
        self._agents: dict[UUID, AgentHandle] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}  # Prevent concurrent send_message

    async def start_agent(
        self,
        definition_id: str,
        parent_transcript_id: UUID | None = None,
        inherit_mounts_from: UUID | None = None,
    ) -> UUID:
        transcript_id = uuid4()

        # Create agent_runs record
        create_agent_run(
            transcript_id,
            definition_id,
            parent=parent_transcript_id,
        )

        # Start container + MCP server (long-running)
        handle = await AgentHandle.create(
            transcript_id=transcript_id,
            definition_id=definition_id,
            inherit_mounts_from=inherit_mounts_from,
        )

        self._agents[transcript_id] = handle
        self._locks[transcript_id] = asyncio.Lock()
        return transcript_id

    async def send_message(self, transcript_id: UUID, message: str) -> str:
        handle = self._agents.get(transcript_id)
        if handle is None:
            raise ValueError(f"No agent with transcript_id {transcript_id}")

        async with self._locks[transcript_id]:
            # Check if container died, restart if needed
            if not handle.container.is_alive():
                await handle.restart_container()
                handle.inject_restart_message()

            # Add message and run until text response
            return await handle.send_and_wait_for_text(message)

    async def cleanup(self, transcript_id: UUID):
        """Cleanup a specific agent."""
        handle = self._agents.pop(transcript_id, None)
        if handle:
            await handle.shutdown()

    async def cleanup_all(self):
        """Cleanup all agents (e.g., on process exit)."""
        for handle in self._agents.values():
            await handle.shutdown()
        self._agents.clear()


@dataclass
class AgentHandle:
    """Handle to a single long-running agent.

    State held per agent:
    - transcript_id: unique identifier, also PK in agent_runs table
    - agent: the Agent instance (owns transcript in _transcript)
    - compositor: manages container + MCP server lifecycle
    - config: for restart (definition_id, mounts, model, etc.)

    Key insight: Agent.run() is resumable. It resets `finished=False` but
    preserves `_transcript`. So send_and_wait_for_text() just:
    1. Inserts user message
    2. Calls agent.run() - continues from existing transcript
    3. Returns when AbortOnTextMessage handler stops the loop

    Events are persisted to DB via DatabaseEventHandler (for crash recovery
    if the process dies - can reconstruct Agent from DB events).
    """

    transcript_id: UUID
    agent: Agent                      # Agent instance (owns transcript)
    compositor: PropertiesDockerCompositorHTTP  # Container + MCP lifecycle
    db_handler: DatabaseEventHandler  # For explicit persistence (system messages)
    text_capture_handler: CaptureTextHandler  # Captures text + aborts
    config: AgentConfig               # For restart: definition_id, mounts, model, etc.

    @classmethod
    async def create(
        cls,
        transcript_id: UUID,
        definition_id: str,
        inherit_mounts_from: UUID | None,
        model_client: OpenAIModelProto,
    ) -> "AgentHandle":
        # 1. Load definition from DB
        definition = load_definition(definition_id)

        # 2. Unpack to temp workspace
        workspace = tempfile.mkdtemp(prefix=f"agent_{transcript_id}_")
        unpack_definition(definition.archive, workspace)

        # 3. Create compositor (manages container, MCP server, hydration)
        # PropertiesDockerCompositorHTTP handles:
        # - Docker container with mounts
        # - MCP-over-HTTP server
        # - Environment variables (PG creds, MCP_SERVER_URL, etc.)
        compositor = await create_compositor(
            workspace=workspace,
            definition_id=definition_id,
            inherit_mounts_from=inherit_mounts_from,
        )

        # 4. Create handlers
        db_handler = DatabaseEventHandler(transcript_id=transcript_id)
        text_capture = CaptureTextHandler()  # Captures text, aborts loop

        # 5. Create Agent with handlers
        async with Client(compositor) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=model_client,
                handlers=[
                    db_handler,
                    text_capture,
                    # ... other handlers
                ],
                tool_policy=AllowAnyToolOrTextMessage(),
                dynamic_instructions=lambda: (Path(workspace) / "AGENT.md").read_text(),
            )

        # 5. Run init script, inject as first assistant message (warm-start)
        init_output = await compositor.runtime.server.docker_exec(["./init"])
        agent.insert_message(AssistantMessage.text(init_output))

        return cls(
            transcript_id=transcript_id,
            agent=agent,
            compositor=compositor,
            db_handler=db_handler,
            text_capture_handler=text_capture,
            config=AgentConfig(definition_id, workspace, inherit_mounts_from, model_client),
        )

    async def send_and_wait_for_text(self, message: str) -> str:
        """Send message and run agent until it produces text response."""
        # Add user message to agent's transcript
        self.agent.insert_message(UserMessage.text(message))

        # Run agent loop - CaptureTextHandler captures and aborts on text
        await self.agent.run()
        return self.text_capture_handler.take()  # Returns captured text, clears state

    async def restart_container(self):
        """Restart container after it was killed."""
        # Restart container
        await self.compositor.runtime.server.start()

        # Agent transcript is preserved (Agent.run() doesn't clear _transcript)
        # Inject restart notification - will be persisted on next run()
        self.agent.insert_message(SystemMessage.text(
            "Your container was restarted. Any local state (files in /tmp, "
            "running processes, environment variables set at runtime) has been "
            "lost. The conversation history and mounted volumes are preserved."
        ))
        # Persist directly via db handler (insert_message doesn't trigger handlers)
        self.db_handler.on_system_text(self.transcript_id, "container_restart")

    async def shutdown(self):
        """Clean up all resources."""
        await self.compositor.__aexit__(None, None, None)
        shutil.rmtree(self.config.workspace)
```

**CaptureTextHandler for conversational interface:**

```python
class CaptureTextHandler(BaseHandler):
    """Capture assistant text and abort loop for conversational use.

    Unlike FinishOnTextMessageHandler which just aborts, this handler
    captures the text so it can be retrieved after run() completes.
    """

    def __init__(self):
        self._captured: str | None = None
        self._should_abort = False

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """Capture text and set abort flag."""
        self._captured = evt.text
        self._should_abort = True

    def on_before_sample(self) -> LoopDecision:
        """Abort if text was captured."""
        if self._should_abort:
            self._should_abort = False
            return Abort()
        return NoAction()

    def take(self) -> str:
        """Return captured text and clear state for next run()."""
        text = self._captured
        self._captured = None
        if text is None:
            raise RuntimeError("No text captured - agent may have been aborted for other reason")
        return text
```

**Required infrastructure extension for system message persistence:**

Currently `Agent.insert_message()` does not notify handlers (by design - for setup).
To persist system messages like restart notifications:

1. Add `SystemText` event type to `events.py`:
   ```python
   class SystemText(BaseModel):
       type: Literal["system_text"] = "system_text"
       text: str
       tag: str | None = None  # Optional: "container_restart", "context_injected", etc.
   ```

2. Add `on_system_text_event` to `BaseHandler`:
   ```python
   def on_system_text_event(self, evt: SystemText) -> None:
       """Called when a system message is injected."""
       return
   ```

3. Extend `DatabaseEventHandler` to persist:
   ```python
   def on_system_text(self, transcript_id: UUID, tag: str | None = None) -> None:
       self._write_event(SystemText(text=..., tag=tag))
   ```

4. Update `Agent._notify_handlers_for_transcript_item` to call the hook:
   ```python
   elif isinstance(item, SystemMessage):
       text = self._extract_text_from_message(item)
       for h in self._handlers:
           h.on_system_text_event(SystemText(text=text))
   ```

Alternatively, `AgentHandle` keeps a reference to the `DatabaseEventHandler` and
calls it directly after `insert_message()`, as shown in `restart_container()` above.

**Usage patterns:**

```python
# Prompt optimizer running critics
registry = AgentRegistry()
critic_id = await registry.start_agent("critic", parent_transcript_id=my_transcript)
result = await registry.send_message(critic_id, "Review this code...")

# Agent spawning sub-agent for task decomposition
sub_id = await registry.start_agent(
    "freeform_abc123",
    parent_transcript_id=current_transcript_id(),
    inherit_mounts_from=current_transcript_id(),
)
response = await registry.send_message(sub_id, "Trace the auth flow...")

# CLI running any agent
registry = AgentRegistry()
agent_id = await registry.start_agent("grader")
```

**Key properties:**
- Same infrastructure for all agent execution
- Container stays alive between `send_message` calls
- Agent.run() is resumable - doesn't clear `_transcript`, just resets `finished` flag
- Events persisted to DB via `DatabaseEventHandler` (for crash recovery)
- Lock prevents concurrent `send_message` to same agent
- Restart: container restarted, inject system message, transcript already in memory
- Uses existing `Agent.run()` loop with `AbortOnTextMessage` handler to stop when text produced

### Use Cases

- **Architecture tracing**: "Go trace how requests flow from API to database"
- **Targeted analysis**: "Look specifically for type errors in the models/ directory"
- **Parallel review**: Spawn multiple sub-agents for different file groups
- **Iterative refinement**: Sub-agent finds issues, parent synthesizes

### Prompt Optimizer Awareness

The prompt optimizer agent should know about sub-agent spawning so it can:
- Teach critics to decompose complex reviews into sub-tasks
- Add sub-agent patterns to critic AGENT.md (e.g., "For large codebases, spawn
  sub-agents to analyze different modules in parallel")
- Evolve effective sub-agent prompts alongside the main critic prompt
- Optimize the division of labor between parent and child agents

This is documented in the prompt optimizer's own AGENT.md and referenced when
evolving critic definitions.
