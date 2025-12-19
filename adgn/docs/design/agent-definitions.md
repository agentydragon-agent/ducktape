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

from importlib.resources import files

# Read MCP connection info from adgn package resources
print(files('adgn.props.prompts').joinpath('mcp_http_connection.md').read_text())

# Scope info (snapshot slug, files) is available via MCP resources
# The agent reads these via resources.read() during its operation
print("=== Environment Ready ===")
print("Use resources.read() to access snapshot_slug and scope_files")

# Any agent-specific setup...
```

Exit non-zero to abort agent startup.

### Other files

No restrictions. Common patterns:
- `tools/` - executable scripts the agent can invoke
- `context/` - reference documentation
- `examples/` - worked examples for few-shot guidance

## Agent Types

Agent types are defined as enums in both Python and PostgreSQL:

```python
from enum import StrEnum

class AgentType(StrEnum):
    """Types of agents in the system."""
    CRITIC = "critic"
    GRADER = "grader"
    PROMPT_OPTIMIZER = "prompt_optimizer"
    FREEFORM = "freeform"  # Ad-hoc sub-agents
```

```sql
CREATE TYPE agent_type AS ENUM (
    'critic',
    'grader',
    'prompt_optimizer',
    'freeform'
);
```

All code must use these enum values, never raw strings.

## Storage

### Unified Agent Runs Table

Instead of separate `critic_runs`, `grader_runs`, `prompt_optimization_runs` tables,
use a single unified table with agent-type-specific columns and CHECK constraints:

```sql
CREATE TABLE agent_runs (
    transcript_id UUID PRIMARY KEY,
    agent_definition_id TEXT NOT NULL REFERENCES agent_definitions(id),
    status TEXT NOT NULL DEFAULT 'running',
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Provenance: which agent spawned this one? (FK enforced)
    parent_transcript_id UUID REFERENCES agent_runs(transcript_id),

    -- Common columns
    model TEXT NOT NULL,

    -- Type-specific config stored as JSONB (Pydantic serde)
    -- Contains agent_type discriminator + type-specific fields
    -- e.g., {"agent_type": "critic", "snapshot_slug": "...", "scope_hash": "..."}
    type_config JSONB NOT NULL,

    -- Output (JSONB, structure depends on agent_type)
    output JSONB
);

-- Extract agent_type from JSONB for indexing
CREATE INDEX idx_agent_runs_type ON agent_runs((type_config->>'agent_type'));
CREATE INDEX idx_agent_runs_parent ON agent_runs(parent_transcript_id);
-- Partial index for critic snapshot lookups
CREATE INDEX idx_agent_runs_snapshot ON agent_runs((type_config->>'snapshot_slug'))
    WHERE type_config->>'agent_type' = 'critic';
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
-- Granular read access to agent definitions:
-- 1. Built-in (repo-synced) definitions: readable by all agents
-- 2. Prompt optimizer: can read ALL definitions (needs to analyze and evolve them)
-- 3. Other agents: can read their own instantiation definition + definitions they created
CREATE POLICY read_definitions ON agent_definitions
    FOR SELECT
    USING (
        -- Built-in (repo-synced) definitions are readable by all
        created_by_transcript_id IS NULL
        -- OR prompt optimizer can read all (needs full visibility to evolve agents)
        OR EXISTS (
            SELECT 1 FROM agent_runs
            WHERE transcript_id = current_transcript_id()
            AND agent_type = 'prompt_optimizer'
        )
        -- OR this is the definition the agent was instantiated from (self-awareness)
        OR id = (SELECT agent_definition_id FROM agent_runs WHERE transcript_id = current_transcript_id())
        -- OR the agent created this definition (own creations)
        OR created_by_transcript_id = current_transcript_id()
    );

-- Only prompt_optimizer and critic can create new definitions
-- (grader just evaluates, doesn't evolve agent definitions)
CREATE POLICY insert_own ON agent_definitions
    FOR INSERT
    WITH CHECK (
        created_by_transcript_id = current_transcript_id()
        AND EXISTS (
            SELECT 1 FROM agent_runs
            WHERE transcript_id = current_transcript_id()
            AND agent_type IN ('prompt_optimizer', 'critic')
        )
    );

-- No UPDATE or DELETE allowed (definitions are immutable, create new versions instead)
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
from adgn.props.agent_helpers import fetch_agent_definition

# Fetch a specific definition by ID
fetch_agent_definition(definition_id="critic_a1b2c3", target_dir=Path("/workspace/agents/critic_a1b2c3"))

# Fetch the baseline critic definition
fetch_agent_definition(definition_id="critic", target_dir=Path("/workspace/agents/critic"))

# Fetch own definition (uses environment variable set by runtime)
fetch_agent_definition(self=True, target_dir=Path("/workspace/agents/self"))
```

### CLI

Part of the existing `agent-helpers` subcommand:

```bash
# Fetch by ID
agent-helpers agent-definition fetch critic_a1b2c3 /workspace/agents/critic_a1b2c3

# Fetch baseline (just use the readable ID)
agent-helpers agent-definition fetch critic /workspace/agents/critic

# Fetch self (uses current agent's definition from AGENT_DEFINITION_ID env var)
agent-helpers agent-definition fetch --self /workspace/agents/self
```

### Bootstrap Integration (Warm-Start)

The agent runtime automatically:
1. Unpacks agent definition to `/workspace`
2. Sets environment variables (`AGENT_DEFINITION_ID`, `MCP_SERVER_URL`, `PGHOST`, etc.)
3. Reads `/workspace/AGENT.md` as system prompt (via `dynamic_instructions`)
4. Injects `./init` execution as bootstrap tool call (via `SequenceHandler`)
5. Agent loop executes init via standard MCP docker_exec flow
6. Init output becomes part of transcript as tool result (warm-start)
7. Agent begins sampling with init context already visible

```python
# Bootstrap handler injects init execution as first action
builder = TypedBootstrapBuilder.for_server(runtime.server)
init_call = docker_exec_call(builder, runtime, ["./init"], timeout_ms=5000)
bootstrap = SequenceHandler([InjectItems(items=[init_call])])
```

Agent-type-specific context (e.g., `SNAPSHOT_SLUG` for critics) is set by the
compositor that launches that agent type, not by the general runtime.

This pattern ensures the agent sees init output as a tool result in its
transcript, following the existing bootstrap pattern used by critics,
graders, and other agents.

Agents that need to read other definitions (e.g., optimizer reading critic) use
the helper explicitly.

## Workflow: Prompt Optimizer Evolving Critic

```
1. Optimizer starts with access to:
   - Its own definition unpacked at /workspace
   - All agent definitions readable via database
   - Evaluation results showing which definitions perform well

2. Optimizer queries evaluation data to identify promising definitions:
   - Which critic definitions have high scores?
   - Which ones show interesting patterns worth exploring?
   - Decision is data-driven, not hardcoded to built-in definitions

3. Optimizer fetches selected definition(s) for analysis:
   $ agent-helpers agent-definition fetch critic_a1b2c3 /workspace/agents/critic_a1b2c3

4. Optimizer reads and analyzes:
   - /workspace/agents/critic_a1b2c3/AGENT.md
   - /workspace/agents/critic_a1b2c3/tools/...

5. Optimizer creates modified version:
   $ cp -r /workspace/agents/critic_a1b2c3 /workspace/agents/critic_new
   $ edit /workspace/agents/critic_new/AGENT.md
   $ edit /workspace/agents/critic_new/tools/analyze.py

6. Optimizer creates new definition (INSERT via RLS):
   $ agent-helpers agent-definition create --type critic /workspace/agents/critic_new
   # Returns: Created agent definition ID critic_d4e5f6

7. Optimizer runs critic with new definition:
   $ agent-helpers run-critic --definition critic_d4e5f6 --snapshot ducktape/2025-01-15
```

## Migration Path

### Phase 1: Schema + Helpers
- Add `agent_definitions` table
- Implement `fetch_agent_definition` and `create_agent_definition` helpers
- Add CLI wrappers (`agent-helpers agent-definition fetch/create`)

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

2. **Database credentials**:
   - Passed via environment variables (`$PGHOST`, `$PGUSER`, etc.)
   - Standard PostgreSQL environment variable pattern

3. **Agent-specific context** (snapshot slug, file scope):
   - Read via MCP resources (already the pattern today)
   - Compositor sets up these resources before agent starts
   - init can read them via resources.read()

4. **MCP server URL/token**:
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

Canonical agent definitions live in git at `adgn/src/adgn/props/agents/`. Synced to
database as part of the existing DB sync command:

```bash
# Existing sync command handles agent definitions too
python -m adgn.props.cli db sync

# This (among other things):
# 1. Walks adgn/src/adgn/props/agents/
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
- [ ] Refactor `Agent.run()` to return `None` instead of `AgentResult`
  - All result capture should be done via handlers (e.g., `CaptureTextHandler`)
  - Cleaner separation: agent loop just runs, handlers capture what they need
  - Remove `assistant_text_chunks` accumulation from Agent class
  - Existing code using `result.text` migrates to handler-based capture

## Future: Sub-Agent Spawning

Agents can spawn sub-agents for task decomposition. A critic might say "go trace the
architecture" or "look for type errors" and delegate to specialized sub-agents.

### Workflow

1. Parent agent creates ad-hoc agent definition directory:
   ```bash
   $ mkdir /workspace/subagents/code-tracer
   $ cat > /workspace/subagents/code-tracer/AGENT.md << 'EOF'
   You are a code tracer. Analyze how data flows from X to Y.

   ## Your Task
   Trace the data flow and report your findings.
   EOF
   $ cat > /workspace/subagents/code-tracer/init << 'EOF'
   #!/bin/bash
   echo "Code tracer ready"
   EOF
   $ chmod +x /workspace/subagents/code-tracer/init
   ```

2. Parent registers the definition:
   ```bash
   $ agent-helpers agent-definition create --type freeform /workspace/subagents/code-tracer
   # Returns: Created agent definition ID freeform_abc123
   ```

3. Parent spawns sub-agent via MCP tool:
   ```python
   result = spawn_subagent(
       definition_id="freeform_abc123",
       inherit_mounts=True,  # same snapshot, same /workspace access
       # parent_transcript_id automatically set to current_transcript_id()
   )
   # Blocks until sub-agent completes, returns output
   ```

4. Sub-agent runs with:
   - Its own transcript_id
   - `parent_transcript_id` pointing to parent
   - Same environment (snapshot mounts, DB access)
   - Its ad-hoc AGENT.md as system prompt

5. Parent receives result and continues

### Schema Support

Already handled by unified `agent_runs` table:
- `agent_type = 'freeform'` for ad-hoc sub-agents
- `parent_transcript_id` links to spawning agent
- `agent_definition_id` references the ad-hoc definition

### MCP Tools (Conversational Interface)

Rather than one-shot spawning, sub-agents support continuous conversation:

```python
@mcp.tool()
async def create_agent(
    definition_id: str,
) -> str:
    """Create a sub-agent session.

    Creates a new agent with its own transcript_id, sets up container and
    environment, but does NOT run any turns yet.

    Returns: transcript_id (use with run_agent)
    """

@mcp.tool()
async def run_agent(
    transcript_id: str,
    message: str,
) -> str:
    """Send a message to a sub-agent and run until response.

    Adds the message to the conversation, then runs the agent until it
    produces a text response. Aborts and returns when agent sends text.

    If the container was previously killed (e.g., parent was idle), it will
    be restarted and the agent receives a system message:
    "Your container was restarted. Any local state (files in /tmp, running
    processes, environment variables set at runtime) has been lost. The
    conversation history and mounted volumes are preserved."

    Returns: The agent's text response

    Errors:
    - If agent is already rolling out (concurrent run_agent not allowed)
    - If transcript doesn't exist
    """
```

**Agent-type-specific launcher tools:**

The generic `create_agent`/`run_agent` tools are the low-level building blocks.
Each launcher agent type has specialized MCP tools that wrap these with
appropriate inputs:

```python
# Critic agent's tool for spawning sub-agents (freeform analysis tasks)
@mcp.tool()
async def spawn_analysis_subagent(definition_id: str) -> str:
    """Spawn a sub-agent for code analysis.

    The sub-agent gets:
    - Same snapshot mount as parent (read-only)
    - Unpacked agent definition directory
    - NO other state transferred

    Returns: transcript_id
    """

# Prompt optimizer's tool for running critics
@mcp.tool()
async def run_critic(
    definition_id: str,
    snapshot_slug: str,
    scope_hash: str,
) -> str:
    """Run a critic agent with specified inputs.

    Creates critic, sets up snapshot mount, runs to completion.
    Prompt optimizer doesn't need ongoing conversation with critics.

    Returns: Critic's output (structured critique)
    """

# Prompt optimizer's tool for running graders
@mcp.tool()
async def run_grader(
    definition_id: str,
    graded_transcript_id: str,
) -> str:
    """Run a grader agent on a specific transcript.

    Creates grader, provides transcript to grade, runs to completion.

    Validation:
    - graded_transcript_id must be a critic-type run (rejects other agent types)

    Returns: Grader's output (score + reasoning)
    """
```

**Validation rules:**

Most constraints are enforced by the type system (discriminated union). Only
cross-reference validation remains:

```python
def validate_agent_config(config: AgentConfig) -> None:
    """Validate agent configuration before creation.

    Type-specific required fields are enforced by the Pydantic models.
    This function validates cross-reference constraints.
    """
    if isinstance(config.type_config, GraderTypeConfig):
        # Graders can only grade critic runs
        run = get_agent_run(config.type_config.graded_transcript_id)
        if run.agent_type != AgentType.CRITIC:
            raise ValueError(
                f"Grader can only grade critic runs, got {run.agent_type}"
            )
```

These heterogeneous launcher tools are backed by shared backend code
(AgentRegistry) that handles container lifecycle, message passing, etc.

**Workflow:**
```python
# Critic spawning a sub-agent for architecture analysis
transcript_id = spawn_analysis_subagent(definition_id="freeform_abc123")

# Have a conversation
response1 = run_agent(transcript_id, "Trace how API requests reach the database")
# Agent runs, explores code, responds with findings

response2 = run_agent(transcript_id, "Now focus on the authentication middleware")
# Continues same conversation, agent has context from previous turns

# ... time passes, container gets cleaned up ...

response3 = run_agent(transcript_id, "Summarize your findings")
# Container restarted, agent gets system message about restart, then continues
```

**Prompt optimizer workflow (no conversation needed):**
```python
# Run critic with specific inputs
output = run_critic(
    definition_id="critic_abc123",
    snapshot_slug="ducktape/2025-01-15",
    scope_hash="abc123",
)
# Returns structured critique, no ongoing conversation
```

**State Management:**
- Session identified by transcript_id (no separate session concept)
- Conversation history persisted in events table
- No explicit end_agent needed - resources cleaned up when parent exits

**Persistence for restart:**

Everything needed to restart an agent after app quits must be saved to database:
- `agent_definition_id` - which definition to unpack
- Agent-type-specific context stored in `agent_runs`:
  - Critics: `snapshot_slug` (where to mount snapshot)
  - Graders: `graded_transcript_id`
  - Freeform sub-agents: `parent_transcript_id` (inherit mounts from parent's config)
- Transcript events in `events` table (reconstruct conversation)

On restart:
1. Query `agent_runs` for agent's configuration
2. Re-unpack agent definition to container workspace
3. Reconstruct mounts from stored configuration
4. Rebuild `Agent` from persisted events
5. Continue conversation

### Implementation: Agent Registry

General agent lifecycle management - used by prompt optimizer running critics,
agents spawning sub-agents, CLI, etc. Not sub-agent specific.

```python
from pydantic import BaseModel

# Type-specific config (discriminated union) - only the non-shared fields
class CriticTypeConfig(BaseModel):
    """Critic-specific configuration."""
    agent_type: Literal[AgentType.CRITIC] = AgentType.CRITIC
    snapshot_slug: str
    scope_hash: str


class GraderTypeConfig(BaseModel):
    """Grader-specific configuration."""
    agent_type: Literal[AgentType.GRADER] = AgentType.GRADER
    graded_transcript_id: UUID  # Must be a critic run (validated)


class FreeformTypeConfig(BaseModel):
    """Freeform sub-agent configuration (no extra fields, just type marker)."""
    agent_type: Literal[AgentType.FREEFORM] = AgentType.FREEFORM


class PromptOptimizerTypeConfig(BaseModel):
    """Prompt optimizer configuration (no extra fields, just type marker)."""
    agent_type: Literal[AgentType.PROMPT_OPTIMIZER] = AgentType.PROMPT_OPTIMIZER


# Discriminated union for type-specific config only
TypeConfig = Annotated[
    CriticTypeConfig | GraderTypeConfig | FreeformTypeConfig | PromptOptimizerTypeConfig,
    Field(discriminator="agent_type"),
]


@dataclass
class AgentConfig:
    """Full agent configuration - shared fields + type-specific config.

    Shared fields are at the top level. Type-specific fields are in `type_config`.
    The `type_config` is stored as JSONB in the database for easy serde.
    """
    definition_id: str
    parent_transcript_id: UUID | None  # FK to agent_runs, explicit None or UUID
    type_config: TypeConfig            # Pydantic model, stored as JSONB

    @property
    def agent_type(self) -> AgentType:
        return self.type_config.agent_type


class AgentRegistry:
    """Manages long-running agent containers."""

    def __init__(self):
        self._agents: dict[UUID, AgentHandle] = {}

    async def create_agent(
        self,
        config: AgentConfig,
    ) -> UUID:
        transcript_id = uuid4()

        # Create agent_runs record (persists all config for restart)
        create_agent_run(
            transcript_id=transcript_id,
            definition_id=config.definition_id,
            parent_transcript_id=config.parent_transcript_id,
            type_config=config.type_config.model_dump(),  # Pydantic -> JSONB
        )

        # Start container + MCP server (long-running)
        handle = await AgentHandle.create(
            transcript_id=transcript_id,
            config=config,
        )

        self._agents[transcript_id] = handle
        return transcript_id

    async def run_agent(self, transcript_id: UUID, message: str) -> str:
        handle = self._agents.get(transcript_id)
        if handle is None:
            raise ValueError(f"No agent with transcript_id {transcript_id}")

        return await handle.run(message)

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
    - workspace: path to unpacked agent definition

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
    text_capture_handler: CaptureTextHandler  # Captures text + aborts
    config: AgentConfig               # For restart
    workspace: Path                   # Unpacked agent definition
    _lock: asyncio.Lock               # Prevent concurrent run() calls

    @classmethod
    async def create(
        cls,
        transcript_id: UUID,
        config: AgentConfig,
        model_client: OpenAIModelProto,
    ) -> "AgentHandle":
        # 1. Load definition from DB
        definition = load_definition(config.definition_id)

        # 2. Unpack to temp workspace
        workspace = Path(tempfile.mkdtemp(prefix=f"agent_{transcript_id}_"))
        unpack_definition(definition.archive, workspace)

        # 3. Create compositor (manages container, MCP server, hydration)
        # PropertiesDockerCompositorHTTP handles:
        # - Docker container with mounts (based on agent type + config)
        # - MCP-over-HTTP server
        # - Environment variables (PG creds, MCP_SERVER_URL, etc.)
        compositor = await create_compositor(
            workspace=workspace,
            config=config,  # Agent-type-specific mounts derived from config
        )

        # 4. Create bootstrap handler for init execution
        builder = TypedBootstrapBuilder.for_server(compositor.runtime.server)
        init_call = docker_exec_call(builder, compositor.runtime, ["./init"], timeout_ms=5000)
        bootstrap = SequenceHandler([InjectItems(items=[init_call])])

        # 5. Create handlers
        db_handler = DatabaseEventHandler(transcript_id=transcript_id)
        text_capture = CaptureTextHandler()  # Captures text, aborts loop

        # 6. Create Agent with handlers
        async with Client(compositor) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=model_client,
                handlers=[
                    bootstrap,       # First: execute ./init via docker_exec
                    db_handler,      # Persist all events (including init output)
                    text_capture,    # Capture text + abort
                    # ... other handlers
                ],
                tool_policy=AllowAnyToolOrTextMessage(),
                dynamic_instructions=lambda: (workspace / "AGENT.md").read_text(),
            )
        # Note: init output is now in transcript as tool result from bootstrap

        return cls(
            transcript_id=transcript_id,
            agent=agent,
            compositor=compositor,
            text_capture_handler=text_capture,
            config=config,
            workspace=workspace,
            _lock=asyncio.Lock(),
        )

    async def run(self, message: str) -> str:
        """Send message and run agent until it produces text response.

        Thread-safe: only one run() call can execute at a time.
        """
        async with self._lock:
            # Check if container died, restart if needed
            if not self.compositor.container.is_alive():
                await self.restart_container()

            # Add user message to agent's transcript
            self.agent.insert_message(UserMessage.text(message))

            # Run agent loop - CaptureTextHandler captures and aborts on text
            await self.agent.run()
            return self.text_capture_handler.take()  # Returns captured text, clears state

    async def restart_container(self):
        """Restart container after it was killed.

        Re-unpacks agent definition to ensure workspace is intact.
        """
        # Re-unpack agent definition (container workspace was lost)
        definition = load_definition(self.config.definition_id)
        unpack_definition(definition.archive, self.workspace)

        # Restart container
        await self.compositor.runtime.server.start()

        # Insert restart notification - triggers handlers, so DB persists it
        self.agent.insert_message(SystemMessage.text(
            "Your container was restarted. Any local state (files in /tmp, "
            "running processes, environment variables set at runtime) has been "
            "lost. The conversation history and mounted volumes are preserved."
        ))

    async def shutdown(self):
        """Clean up all resources."""
        await self.compositor.__aexit__(None, None, None)
        shutil.rmtree(self.workspace)
```

**New handler for conversational interface:**

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

**Required infrastructure extensions:**

1. **Modify `Agent.insert_message()` to trigger handlers:**
   ```python
   def insert_message(self, message: Message) -> None:
       """Insert message into transcript and notify handlers."""
       self._transcript.append(message)
       self._notify_handlers_for_transcript_item(message)
   ```

   **Compatibility verified:** No code in the repo depends on `insert_message` NOT
   triggering handlers. Benefits:
   - Complete transcripts in DB (includes initial system/user messages)
   - Simpler API (no separate method needed)
   - Display handlers can show setup if desired

2. **Add `SystemText` event type** to `events.py`:
   ```python
   class SystemText(BaseModel):
       type: Literal["system_text"] = "system_text"
       text: str
   ```

3. **Add `on_system_text_event` to `BaseHandler`** (currently `pass` for SystemMessage):
   ```python
   def on_system_text_event(self, evt: SystemText) -> None:
       """Called when a system message is inserted."""
       return
   ```

4. **Extend `DatabaseEventHandler`** to persist system messages.

5. **Update `Agent._notify_handlers_for_transcript_item`** to call the hook:
   ```python
   elif isinstance(item, SystemMessage):
       text = self._extract_text_from_message(item)
       for h in self._handlers:
           h.on_system_text_event(SystemText(text=text))
   ```

**Usage patterns:**

```python
# Prompt optimizer running critics (spawned by optimizer)
registry = AgentRegistry()
critic_id = await registry.create_agent(AgentConfig(
    definition_id="critic_abc123",
    parent_transcript_id=optimizer_transcript_id,  # Spawned by optimizer
    type_config=CriticTypeConfig(
        snapshot_slug="ducktape/2025-01-15",
        scope_hash="abc123",
    ),
))
result = await registry.run_agent(critic_id, "Begin review")
# Critic runs to completion, returns structured output

# Critic spawning sub-agent for task decomposition
sub_id = await registry.create_agent(AgentConfig(
    definition_id="freeform_abc123",
    parent_transcript_id=current_transcript_id(),  # Inherits snapshot mount
    type_config=FreeformTypeConfig(),
))
response = await registry.run_agent(sub_id, "Trace the auth flow...")

# CLI running grader (top-level, no parent)
registry = AgentRegistry()
agent_id = await registry.create_agent(AgentConfig(
    definition_id="grader",
    parent_transcript_id=None,  # Top-level invocation from CLI
    type_config=GraderTypeConfig(
        graded_transcript_id=some_critic_transcript,
    ),
))
```

**Key properties:**
- Same infrastructure for all agent execution
- Container stays alive between `run_agent` calls
- Agent.run() is resumable - doesn't clear `_transcript`, just resets `finished` flag
- Events persisted to DB via `DatabaseEventHandler` (for crash recovery)
- Lock inside AgentHandle prevents concurrent runs to same agent
- Restart: container restarted, re-unpack definition, inject system message
- Uses existing `Agent.run()` loop with `CaptureTextHandler` to stop when text produced

### Use Cases

- **Architecture tracing**: "Go trace how requests flow from API to database"
- **Targeted analysis**: "Look specifically for type errors in the models/ directory"
- **Parallel review**: Spawn multiple sub-agents for different file groups
- **Iterative refinement**: Sub-agent finds issues, parent synthesizes

### Prompt Optimizer Role

The prompt optimizer's job extends beyond just writing system prompts:

1. **System prompts**: Evolve AGENT.md to improve agent effectiveness
2. **Tool development**: Create and refine helper scripts in agent definitions
   that help agents do their job well (e.g., analysis tools, formatters)
3. **Sub-agent delegation**: Teach agents to effectively delegate work to
   sub-agents for complex tasks
4. **End-to-end optimization**: Improve the full agent definition package,
   not just the prompt

The optimizer should know about sub-agent spawning so it can:
- Teach critics to decompose complex reviews into sub-tasks
- Add sub-agent patterns to critic AGENT.md (e.g., "For large codebases, spawn
  sub-agents to analyze different modules in parallel")
- Evolve effective sub-agent prompts alongside the main critic prompt
- Optimize the division of labor between parent and child agents

### Prompt Improver Agent

The prompt improver agent (a specific instantiation of prompt optimizer):
- Has access to agent definitions of rollouts it should analyze
- Can read evaluation results to understand what works
- Creates new agent definitions as its output
- **Output**: The new agent definition ID (its return value IS the definition)

```python
# Prompt improver's workflow
# 1. Read eval results to find promising directions
# 2. Fetch and analyze existing definitions
# 3. Create improved definition (AGENT.md + tools)
# 4. Register via: agent-helpers agent-definition create --type critic /workspace/improved
# 5. Return the new definition_id as output
```

This is documented in the prompt improver's own AGENT.md.
