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

**All provenance tracking uses `agent_run_id`** - the unique identifier for a specific
agent run. This replaces:
- Separate `critic_runs`, `grader_runs`, `prompt_optimization_runs` tables → unified `agent_runs`
- Separate `prompt_optimization_run_id`, `improvement_run_id` columns → `created_by_agent_run_id`

Benefits:
- Single consistent pattern across all tables
- Direct link to full agent transcript for debugging
- **One `agent_runs` table** instead of per-agent-type tables
- Simpler RLS policies (just check `current_agent_run_id()`)
- Lineage via `parent_agent_run_id` in `agent_runs`

Tables using `created_by_agent_run_id` for provenance:
- `agent_definitions` - which agent created this definition
- `prompts` - which agent created this prompt (replaces `prompt_optimization_run_id`, `improvement_run_id`)
- Any other artifact table

For repo-backed/manual entries, `created_by_agent_run_id` is NULL.

## Directory Structure

Agent definitions are self-contained packets. Components cross-reference each other
naturally - docs reference examples, init prints required reading, etc.

```
<agent_definition>/
├── AGENT.md              # System prompt (required)
├── init                  # Runs on agent startup (required, must be executable)
├── docs/                 # Reference documentation
│   └── mcp_http_connection.md  # "see examples/mcp_use.py"
├── examples/             # Runnable code samples
│   └── mcp_use.py        # MCP client example agent can read/run
└── tools/                # Executable tools agent can invoke
```

Built-in agent definitions are compiled from source files at build time. Shared
resources (like `mcp_use.py`) are copied into each definition's archive from a
single source in the git repo.

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

Init reads required documentation from the agent's own workspace:

```python
#!/usr/bin/env python3
"""Init script for critic agent."""
from pathlib import Path

workspace = Path("/workspace")

# Print required reading - MCP connection docs
print(workspace.joinpath("docs/mcp_http_connection.md").read_text())

# Scope info (snapshot slug, files) is available via MCP resources
print("=== Environment Ready ===")
print("Use resources.read() to access snapshot_slug and scope_files")
print("For MCP client example, see: examples/mcp_use.py")

# Any agent-specific setup...
```

Exit non-zero to abort agent startup.

### Other files

No restrictions. Common patterns:
- `docs/` - reference documentation (init prints required reading)
- `examples/` - runnable code samples (docs reference these)
- `tools/` - executable scripts the agent can invoke

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
    agent_run_id UUID PRIMARY KEY,
    agent_definition_id TEXT NOT NULL REFERENCES agent_definitions(id),
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Provenance: which agent spawned this one? (FK enforced)
    parent_agent_run_id UUID REFERENCES agent_runs(agent_run_id),

    -- Common columns
    model TEXT NOT NULL,

    -- Type-specific config stored as JSONB (Pydantic serde)
    -- Contains agent_type discriminator + type-specific fields
    -- e.g., {"agent_type": "critic", "snapshot_slug": "...", "scope_hash": "..."}
    type_config JSONB NOT NULL
);

-- No status/output columns - agents write results to their domain-specific tables:
-- - Critics: issues, critique_comments, etc.
-- - Graders: grader_evaluations
-- - Prompt optimizer: creates new agent_definitions, agent_runs

-- Extract agent_type from JSONB for indexing
CREATE INDEX idx_agent_runs_type ON agent_runs((type_config->>'agent_type'));
CREATE INDEX idx_agent_runs_parent ON agent_runs(parent_agent_run_id);
-- Partial index for critic snapshot lookups
CREATE INDEX idx_agent_runs_snapshot ON agent_runs((type_config->>'snapshot_slug'))
    WHERE type_config->>'agent_type' = 'critic';
```

Benefits:
- **agent_run_id is THE universal identifier** for any agent run
- Lineage via `parent_agent_run_id` - trivial to trace "who spawned who"
- Easy cross-agent queries
- Type-specific constraints enforced by Pydantic models

The `events` table already uses `agent_run_id` as FK, so tool calls link naturally.

### Agent Definitions Schema

```sql
CREATE TABLE agent_definitions (
    id TEXT PRIMARY KEY,                   -- readable: 'critic', 'grader', or auto-generated
    agent_type agent_type NOT NULL,        -- enum: critic, grader, prompt_optimizer, freeform
    archive BYTEA NOT NULL,                -- uncompressed tar archive
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Provenance (set when created by an agent, NULL for repo-backed)
    created_by_agent_run_id UUID          -- transcript of agent that created this definition
);

-- Index for finding definitions by type
CREATE INDEX idx_agent_definitions_type ON agent_definitions(agent_type);
```

ID conventions:
- Repo-backed: readable names like `"critic"`, `"grader"`, `"prompt_optimizer"`
- Agent-created: auto-generated (e.g., `"critic_a1b2c3"` or UUID)

Agents can INSERT directly into this table (with RLS ensuring they can only insert
rows where `created_by_agent_run_id` matches their transcript). No UPDATE allowed.

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

### Role-Based Access

Agents connect to PostgreSQL with individual credentials:
- Username format: `agent_<agent_run_id>` (e.g., `agent_550e8400-e29b-41d4-a716-446655440000`)
- One uniform role setup - privileges determined by querying the agent's config/type
- No separate roles per agent type

```sql
-- Helper function to get current agent's type
CREATE FUNCTION current_agent_type() RETURNS agent_type AS $$
    SELECT (type_config->>'agent_type')::agent_type
    FROM agent_runs
    WHERE agent_run_id = current_agent_run_id()
$$ LANGUAGE SQL STABLE;

-- Helper to get current agent_run_id from session username
CREATE FUNCTION current_agent_run_id() RETURNS UUID AS $$
    SELECT substring(current_user from 'agent_(.+)')::uuid
$$ LANGUAGE SQL STABLE;
```

### Role Lifecycle

Roles are **persistent** with deterministic passwords:

```sql
-- Salt stored in admin-only table (auto-generated if missing)
CREATE TABLE agent_role_salt (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton
    salt BYTEA NOT NULL DEFAULT gen_random_bytes(32)
);
-- Only admin can access
REVOKE ALL ON agent_role_salt FROM PUBLIC;

-- Password derivation: hash(salt, agent_run_id)
-- SECURITY DEFINER runs as owner (admin), but we DON'T grant execute to agents
CREATE FUNCTION derive_agent_password(run_id UUID) RETURNS TEXT AS $$
    SELECT encode(
        sha256((SELECT salt FROM agent_role_salt) || run_id::text::bytea),
        'hex'
    )
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- CRITICAL: No GRANT to agent_base - only admin can call this
-- Alternative: implement password derivation in Python instead of SQL
-- Either way, agents must NOT be able to derive passwords for other agents
```

**Role creation** (on agent creation, never dropped):
```sql
-- Called by runtime when creating agent
CREATE FUNCTION create_agent_role(run_id UUID) RETURNS VOID AS $$
DECLARE
    username TEXT := 'agent_' || run_id::text;
    password TEXT := derive_agent_password(run_id);
BEGIN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', username, password);
    EXECUTE format('GRANT agent_base TO %I', username);  -- inherit base permissions
END
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

Benefits:
- **One user manager** - uniform role setup for all agent types
- **Resume-friendly** - password is deterministic, no need to store/retrieve
- **No cleanup** - roles persist, no race conditions on drop
- **RLS determines access** - all agents share `agent_base` role, RLS policies differentiate by type

### Domain-Specific Tables

Agents write results to domain-specific tables (not to agent_runs):

**Critic output tables (writes):**
```sql
-- Issues discovered by critics
CREATE TABLE issues (
    id UUID PRIMARY KEY,
    agent_run_id UUID NOT NULL REFERENCES agent_runs(agent_run_id),
    file_path TEXT NOT NULL,
    line_number INTEGER,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
-- Note: No severity/category columns.
```

**Grader tables:**
```sql
-- Ground truth data (read by graders)
CREATE TABLE ground_truth_issues (
    id UUID PRIMARY KEY,
    snapshot_slug TEXT NOT NULL,
    file_path TEXT NOT NULL,
    line_number INTEGER,
    description TEXT NOT NULL
    -- RLS: graders can read all ground truth
);

-- Grader evaluations (written by graders)
CREATE TABLE grader_evaluations (
    id UUID PRIMARY KEY,
    agent_run_id UUID NOT NULL REFERENCES agent_runs(agent_run_id),  -- grader's own
    graded_agent_run_id UUID NOT NULL REFERENCES agent_runs(agent_run_id),  -- critic being graded
    issue_id UUID REFERENCES issues(id),
    verdict TEXT NOT NULL,  -- 'true_positive', 'false_positive', 'missed', etc.
    reasoning TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### RLS Policies by Agent Type

**events table:**
```sql
-- ONLY runtime with admin creds inserts events
-- Agents can read their own transcript (SELECT only)
CREATE POLICY agent_read_own_events ON events
    FOR SELECT USING (agent_run_id = current_agent_run_id());

-- Graders can also read transcript of the critic they're grading
CREATE POLICY grader_read_graded_events ON events
    FOR SELECT USING (
        current_agent_type() = 'grader'
        AND agent_run_id = (
            SELECT (type_config->>'graded_agent_run_id')::uuid
            FROM agent_runs WHERE agent_run_id = current_agent_run_id()
        )
    );

-- Prompt optimizer: TRAIN split only (see Split-Based Access section)
```

**agent_definitions table:**
```sql
-- All agents can read repo-synced definitions
CREATE POLICY read_builtin_definitions ON agent_definitions
    FOR SELECT USING (created_by_agent_run_id IS NULL);

-- Prompt optimizer can read ALL definitions
CREATE POLICY optimizer_read_all_definitions ON agent_definitions
    FOR SELECT USING (current_agent_type() = 'prompt_optimizer');

-- Agents can read their own definition
CREATE POLICY read_own_definition ON agent_definitions
    FOR SELECT USING (
        id = (SELECT agent_definition_id FROM agent_runs WHERE agent_run_id = current_agent_run_id())
    );

-- Agents can read definitions they created
CREATE POLICY read_created_definitions ON agent_definitions
    FOR SELECT USING (created_by_agent_run_id = current_agent_run_id());

-- Only prompt_optimizer and critic can create new definitions
CREATE POLICY insert_definitions ON agent_definitions
    FOR INSERT WITH CHECK (
        current_agent_type() IN ('prompt_optimizer', 'critic')
        AND created_by_agent_run_id = current_agent_run_id()
    );
```

**agent_runs table:**
```sql
-- Agents can read their own run
CREATE POLICY read_own_run ON agent_runs
    FOR SELECT USING (agent_run_id = current_agent_run_id());

-- Graders can read the run they're grading
CREATE POLICY grader_read_graded_run ON agent_runs
    FOR SELECT USING (
        current_agent_type() = 'grader'
        AND agent_run_id = (
            SELECT (type_config->>'graded_agent_run_id')::uuid
            FROM agent_runs WHERE agent_run_id = current_agent_run_id()
        )
    );

-- Prompt optimizer: TRAIN split only (see Split-Based Access section)
```

**issues table (critic output):**
```sql
-- Critics can insert issues with their agent_run_id
CREATE POLICY critic_insert_issues ON issues
    FOR INSERT WITH CHECK (
        current_agent_type() = 'critic'
        AND agent_run_id = current_agent_run_id()
    );

-- Graders can read issues from the critic they're grading
CREATE POLICY grader_read_issues ON issues
    FOR SELECT USING (
        current_agent_type() = 'grader'
        AND agent_run_id = (
            SELECT (type_config->>'graded_agent_run_id')::uuid
            FROM agent_runs WHERE agent_run_id = current_agent_run_id()
        )
    );

-- Prompt optimizer: TRAIN split only (see Split-Based Access section)
```

**ground_truth_issues table:**
```sql
-- Graders can ONLY read ground truth for the snapshot they're evaluating
CREATE POLICY grader_read_ground_truth ON ground_truth_issues
    FOR SELECT USING (
        current_agent_type() = 'grader'
        AND snapshot_slug = (
            -- Look up snapshot from the critic run being graded
            SELECT (type_config->>'snapshot_slug')
            FROM agent_runs graded
            WHERE graded.agent_run_id = (
                SELECT (type_config->>'graded_agent_run_id')::uuid
                FROM agent_runs WHERE agent_run_id = current_agent_run_id()
            )
        )
    );

-- Prompt optimizer: TRAIN split only (see Split-Based Access below)
```

**grader_evaluations table:**
```sql
-- Graders can SELECT, INSERT, UPDATE their own evaluations
CREATE POLICY grader_own_evaluations ON grader_evaluations
    FOR ALL USING (
        current_agent_type() = 'grader'
        AND agent_run_id = current_agent_run_id()
    );

-- Prompt optimizer: TRAIN split only (see Split-Based Access below)
```

### Split-Based Access (Prompt Optimizer)

Prompt optimizer has special split-based restrictions to prevent overfitting:

```sql
-- All data access filtered to TRAIN split only
-- Snapshots, issues, ground_truth, grader_evaluations, agent_runs, events
-- are filtered by: snapshot.split = 'TRAIN'

-- VALIDATION split access ONLY via aggregate views/functions:
-- - get_validation_run_aggregates() - returns high-level metrics only
-- - No access to individual issues, ground truth, or grading decisions on VALID split

CREATE POLICY optimizer_train_only_issues ON issues
    FOR SELECT USING (
        current_agent_type() = 'prompt_optimizer'
        AND EXISTS (
            SELECT 1 FROM agent_runs ar
            JOIN snapshots s ON s.slug = (ar.type_config->>'snapshot_slug')
            WHERE ar.agent_run_id = issues.agent_run_id
            AND s.split = 'TRAIN'
        )
    );

-- Similar policies for: ground_truth_issues, grader_evaluations, agent_runs, events
-- All filtered to TRAIN split only

-- Validation access via SECURITY DEFINER function (aggregates only)
GRANT EXECUTE ON FUNCTION get_validation_run_aggregates() TO agent_base;
```

### Access Summary Matrix

| Table | Critic | Grader | Prompt Optimizer | Freeform |
|-------|--------|--------|------------------|----------|
| **events** | SELECT own | SELECT own + graded | SELECT TRAIN only | SELECT own |
| **agent_definitions** | SELECT builtin/own, INSERT freeform | SELECT builtin/own | SELECT all, INSERT critic/grader | SELECT builtin/own |
| **agent_runs** | SELECT own | SELECT own + graded | SELECT TRAIN only | SELECT own |
| **issues** | INSERT own | SELECT graded | SELECT TRAIN only | - |
| **ground_truth_issues** | - | SELECT graded snapshot only | SELECT TRAIN only | - |
| **grader_evaluations** | - | SELECT/INSERT/UPDATE own | SELECT TRAIN only | - |
| **validation aggregates** | - | - | via function only | - |

Note: Events INSERT is done by runtime with admin credentials, not by agents directly.

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
```

Note: Agents don't need to fetch their own definition - it's already unpacked at `/workspace` by the runtime.

### CLI

Part of the existing `agent-helpers` subcommand:

```bash
# Fetch by ID
agent-helpers agent-definition fetch critic_a1b2c3 /workspace/agents/critic_a1b2c3

# Fetch baseline (just use the readable ID)
agent-helpers agent-definition fetch critic /workspace/agents/critic
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

Agent-type-specific context (e.g., snapshot slug for critics) is delivered via
MCP resources attached by the compositor that launches that agent type, not by
environment variables or the general runtime.

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

7. Optimizer runs critic with new definition (via MCP tool):
   agent_run_id = run_critic(
       definition_id="critic_d4e5f6",
       type_config=CriticTypeConfig(
           snapshot_slug="ducktape/2025-01-15",
           scope_hash="abc123",
       ),
       max_turns=200,
   )
   # Read evaluation results from issues table
```

## Implementation Plan

### Security Requirements (must be verified throughout)

These properties MUST be maintained by the implementation:

1. **Password isolation**: Agents must NOT be able to derive passwords for other agents
   - `derive_agent_password` callable only by admin, not by `agent_base` role
   - Alternative: implement password derivation in Python (simpler to secure)

2. **Split-based data isolation**: Prompt optimizer must NOT access validation split directly
   - No access to individual issues, ground truth, or grading decisions on VALID split
   - Validation data only via aggregate views/functions (`get_validation_run_aggregates()`)
   - Prevents overfitting to validation set

3. **Grader snapshot isolation**: Graders can only see ground truth for their evaluated snapshot
   - Not all ground truth data, only the snapshot being graded

4. **Event insertion**: Only runtime with admin credentials inserts events
   - Agents have SELECT only on events table

5. **Two prompt optimizer target metrics** (different validation access):
   - `WHOLE_REPO`: Only full-snapshot validation examples (black-box validation)
     - VALID metrics only via SECURITY DEFINER function (full-snapshot aggregates)
     - Per-file VALID examples blocked entirely
   - `TARGETED`: Both per-file and full-snapshot validation examples
     - VALID examples table accessible (filenames only, no ground truth)
     - VALID metrics via SECURITY DEFINER function (includes per-file aggregates)
   - Both modes: TRAIN ground truth via direct RLS-filtered access
   - Both modes: VALID metrics via SECURITY DEFINER functions only (views can't bypass ground truth RLS)
   - `target_metric` stored in `PromptOptimizerTypeConfig`, used by `current_prompt_optimizer_target_metric()` for RLS

### Development Style Requirements

These requirements apply to all implementation:

1. **Dependency Injection**: Classes that access filesystem paths or environment must:
   - Take dependencies (e.g., `base_path: Path`) as required constructor args (no `None` defaults)
   - Provide `from_env()` classmethod for production use
   - Example: `WorkspaceManager(base_path)` + `WorkspaceManager.from_env()`

2. **Testing**: Tests must:
   - Use DRY fixtures for shared setup
   - Avoid trivial change-detector tests (don't just assert enum values match strings)
   - Test behavior, not implementation details
   - Use parametrized tests where appropriate

3. **Documentation**: Only document what isn't obvious from function/class/argument names and types.

### Phase 0: Independent Refactors

**Completed:**
- ✅ `AgentType` StrEnum + TypeConfig Pydantic models → `adgn/src/adgn/props/agent_types.py`
- ✅ `agent_type_enum` PostgreSQL type → `migrations/versions/20251223000000_add_agent_type_enum.py`
- ✅ `WorkspaceManager` class with DI → `adgn/src/adgn/props/agent_workspace.py`
- ✅ Unified `get_validation_run_aggregates()` → `migrations/versions/20251223000001_unify_validation_aggregates.py`
- ✅ MCP connection docs → `mcp_http_connection.md` references `examples/mcp_use.py` in workspace

**Remaining:**
- `CaptureTextHandler` (needs Docker for agent loop testing)
- `Agent.run()` return type refactor (needs Docker)
- Drop `severity` and `category` columns from `issues` table (not present, skip)
- Rename `transcript_id` to `agent_run_id` (29 files, defer)

### Phase 1: Foundation

1. **Database schema**
   - `agent_definitions` table (uses `agent_type` enum from Phase 0)
   - `agent_runs` unified table (replaces separate critic_runs, grader_runs, etc.)
   - Role lifecycle tables and functions (`agent_role_salt`, `derive_agent_password`, `create_agent_role`)
   - `agent_base` role with RLS policies
   - Indexes

2. **CLI: `agent-helpers agent-definition create`**
   - Pack directory into tar archive
   - Insert into agent_definitions table
   - Validate structure (AGENT.md required, init executable)

3. **CLI: `agent-helpers agent-definition fetch`**
   - Extract from database
   - Unpack to target directory

### Phase 2: Runtime Infrastructure

4. **`AgentHandle.create` (minimal)**
   - Load definition, unpack to workspace
   - Create compositor with workspace mount
   - Run init via bootstrap handler
   - Wire up `dynamic_instructions` from AGENT.md

5. **`AgentRegistry` (minimal)**
   - `create_agent()` - creates record, starts handle
   - `run_agent()` - single message, returns response
   - `_restore_agent()` - reload from database after restart
   - `stop_agent()`, `stop_all()`

### Phase 3: First Migration (Critic)

6. **Sync tooling for repo-tracked definitions**
   - Extend `db sync` to build and upload agent definitions
   - Assemble from shared common bits if needed

7. **Convert critic to AGENT.md format**
   - Extract from `critic_system.j2.md`
   - Create init script
   - Test definition creation + fetch round-trip

8. **Update `CriticAgentEnvironment`**
   - Use AgentRegistry instead of custom setup
   - Verify critic runs work end-to-end

### Phase 4: Sub-agent Support

9. **MCP tools: `create_subagent`, `run_subagent`**
   - Wire to AgentRegistry
   - Handle snapshot mount inheritance from parent

10. **Test sub-agent spawning from critic**
    - Manual test: critic creates freeform sub-agent
    - Verify transcript lineage (parent_agent_run_id)

### Phase 5: Remaining Migrations

11. **Migrate grader**
    - Convert to AGENT.md format
    - Update grader environment

12. **Migrate prompt optimizer**
    - Convert to AGENT.md format
    - Add `run_critic`, `run_grader` MCP tools
    - Separate definitions for different metrics

### Phase 6: Evolution + Cleanup

13. **Wire optimizer to create new definitions**
    - Optimizer can fetch, modify, create new critic definitions
    - Metrics queries that group by definition_id

14. **Drop legacy**
    - Remove `prompts` table
    - Remove Jinja2 templating code
    - Delete `AgentEnvironment` base class and all subclasses:
      - `CriticAgentEnvironment`
      - `GraderAgentEnvironment`
      - `PromptOptimizerAgentEnvironment`
      - `ClusteringAgentEnvironment` (if exists)

**Where per-agent-type logic moves:**

| Current Location | New Location |
|------------------|--------------|
| Jinja2 prompt templates | `AGENT.md` in definition archive |
| Environment-specific mounts | `AgentHandle.create()` derives from `type_config` |
| Handler setup (e.g., FinishOnTextMessage vs FinishOnAgentComplete) | `AgentHandle.create()` chooses based on `agent_type` |
| MCP server class (different per agent type) | `AgentHandle.create()` instantiates based on `agent_type` |
| MCP resources (runtime context like snapshot_slug) | MCP server provides via resources, reads from `type_config` |
| Tool availability | `tools/` directory in definition archive |
| Database credentials setup | Unified: `create_agent_role()` + `derive_agent_password()` |
| Container environment vars | `AgentHandle.create()` sets based on `type_config` |

The key insight: agent-type-specific **behavior** lives in the definition (AGENT.md, init, tools).
Agent-type-specific **infrastructure** (mounts, handlers, MCP server class, DB access) is derived
from `type_config` in `AgentHandle.create()` - a single code path with type-based branching,
not separate classes.

### MVP Checkpoint

Phases 0-3 give you a working critic on the new system. That's the minimum
viable product - everything after builds on that foundation.

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

Canonical agent definitions are synced to database as part of the existing DB sync:

```bash
# Existing sync command handles agent definitions too
python -m adgn.props.cli db sync
```

The git structure doesn't have to match the final agent directory format. The sync
process can assemble agent directories from shared common bits:

- Common tools shared across agents (e.g., `common/tools/`)
- Shared init patterns (e.g., `common/init_templates/`)
- Agent-specific AGENT.md files

The sync builds the final tar archives by combining these pieces, enabling DRY
in the repo while producing self-contained agent definitions in the database.

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
   $ mkdir -p /workspace/subagents/code-tracer
   $ cat > /workspace/subagents/code-tracer/AGENT.md << 'EOF'
   You are a code tracer. Analyze how data flows from X to Y.

   ## Your Task
   Trace the data flow and report your findings.

   ## Environment
   You have access to MCP tools via the MCP-over-HTTP server. Use resources.read()
   to access context provided by the runtime. Use tools like bash, read_file, etc.
   to explore the codebase.

   Report your findings as a structured response when complete.
   EOF
   # Copy shared resources into sub-agent definition
   $ mkdir -p /workspace/subagents/code-tracer/docs /workspace/subagents/code-tracer/examples
   $ cp /workspace/docs/mcp_http_connection.md /workspace/subagents/code-tracer/docs/
   $ cp /workspace/examples/mcp_use.py /workspace/subagents/code-tracer/examples/
   $ cat > /workspace/subagents/code-tracer/init << 'EOF'
   #!/usr/bin/env python3
   """Init script for code tracer sub-agent."""
   from pathlib import Path
   workspace = Path("/workspace")
   print(workspace.joinpath("docs/mcp_http_connection.md").read_text())
   print("=== Code Tracer Ready ===")
   EOF
   $ chmod +x /workspace/subagents/code-tracer/init
   ```

   Sub-agent definitions are self-contained packets just like built-in agents.
   The parent copies shared resources from its own workspace into the sub-agent's
   definition before registering it.

2. Parent registers the definition:
   ```bash
   $ agent-helpers agent-definition create --type freeform /workspace/subagents/code-tracer
   # Returns: Created agent definition ID freeform_abc123
   ```

3. Parent spawns sub-agent via MCP tools:
   ```python
   # Create sub-agent (auto-mounts same snapshot as parent critic)
   agent_run_id = create_subagent(definition_id="freeform_abc123")
   # Have a conversation
   response = run_subagent(agent_run_id, "Trace the data flow from X to Y")
   response2 = run_subagent(agent_run_id, "Now focus on error handling")
   ```

4. Sub-agent runs with:
   - Its own agent_run_id
   - `parent_agent_run_id` pointing to parent
   - Same snapshot mount as parent (handled by `create_subagent`)
   - Its ad-hoc AGENT.md as system prompt

5. Parent receives result and continues

**Note**: Critics use `create_subagent`/`run_subagent` (same snapshot mount).
Prompt optimizer uses `run_critic`/`run_grader` with explicit inputs.

### Schema Support

Already handled by unified `agent_runs` table:
- `agent_definition_id` references the ad-hoc definition (agent_type joined from there)
- `parent_agent_run_id` links to spawning agent

### MCP Tools

**Critic's tools for sub-agents (freeform, text I/O):**

Critics create agent definitions via CLI (`agent-helpers agent-definition create`),
then use these MCP tools to spawn and converse with sub-agents:

```python
@mcp.tool()
async def create_subagent(
    definition_id: str,
) -> UUID:
    """Create a freeform sub-agent.

    Creates a new agent with its own agent_run_id, sets up container and
    environment (same snapshot mount as parent), but does NOT run any turns yet.

    Returns: agent_run_id (use with run_subagent)
    """

@mcp.tool()
async def run_subagent(
    agent_run_id: UUID,
    message: str,
    max_turns: Annotated[int, Field(ge=1, le=500)] = 200,
) -> str:
    """Send a message to a sub-agent and get response.

    Adds the message to the conversation, runs the agent until it
    produces a text response (or hits max_turns).

    If the container was previously killed (e.g., parent was idle), it will
    be restarted and the agent receives a system message about the restart.

    Args:
        max_turns: Maximum turns before stopping. Default 200, must be 1-500.

    Returns: The agent's text response

    Errors:
    - If agent is already running (concurrent calls not allowed)
    - If transcript doesn't exist
    """
```

**Prompt optimizer's tools:**

The prompt optimizer has specialized tools for running critics and graders.
These take the full TypeConfig as a Pydantic model argument:

```python
@mcp.tool()
async def run_critic(
    definition_id: str,
    type_config: CriticTypeConfig,  # Whole config as Pydantic model
    max_turns: Annotated[int, Field(ge=1, le=500)] = 200,
) -> UUID:
    """Run a critic agent with specified inputs.

    Creates critic, sets up snapshot mount, runs to completion (or max_turns).
    Critic runs without user messages - just system prompt + bootstrap.

    Args:
        type_config: CriticTypeConfig with snapshot_slug and scope_hash.
        max_turns: Maximum turns before stopping. Default 200, must be 1-500.

    Returns: agent_run_id (read results from issues table via SQL)
    """

@mcp.tool()
async def run_grader(
    definition_id: str,
    type_config: GraderTypeConfig,  # Whole config as Pydantic model
    max_turns: Annotated[int, Field(ge=1, le=500)] = 200,
) -> UUID:
    """Run a grader agent on a specific transcript.

    Creates grader, provides transcript to grade, runs to completion (or max_turns).
    Grader runs without user messages - just system prompt + bootstrap.

    Args:
        type_config: GraderTypeConfig with graded_agent_run_id (must be critic run).
        max_turns: Maximum turns before stopping. Default 200, must be 1-500.

    Returns: agent_run_id (read results from grader_evaluations table via SQL)
    """
```

Note: Defaults for `max_turns` are only at the MCP tool layer, enforced by
Pydantic `Field(ge=1, le=500)` constraints.

**Validation rules:**

Most constraints are enforced by the type system (discriminated union). Only
cross-reference validation remains:

```python
def validate_agent_config(config: AgentConfig) -> None:
    """Validate agent configuration before creation.

    Type-specific required fields are enforced by the Pydantic models.
    This function validates cross-reference constraints.
    """
    # Validate definition type matches config type
    definition = get_agent_definition(config.definition_id)
    if definition.agent_type != config.agent_type:
        raise ValueError(
            f"Definition {config.definition_id} is type {definition.agent_type}, "
            f"but config specifies {config.agent_type}"
        )

    # Graders can only grade critic runs
    if isinstance(config.type_config, GraderTypeConfig):
        run = get_agent_run(config.type_config.graded_agent_run_id)
        if run.agent_type != AgentType.CRITIC:
            raise ValueError(
                f"Grader can only grade critic runs, got {run.agent_type}"
            )
```

These tools are backed by shared backend code (AgentRegistry) that handles
container lifecycle, message passing, etc.

**Critic workflow (conversational sub-agents):**
```python
# Critic spawning a sub-agent for architecture analysis
agent_run_id = create_subagent(definition_id="freeform_abc123")

# Have a conversation (max_turns=200 is required)
response1 = run_subagent(agent_run_id, "Trace how API requests reach the database", max_turns=200)
# Agent runs, explores code, responds with findings

response2 = run_subagent(agent_run_id, "Now focus on the authentication middleware", max_turns=200)
# Continues same conversation, agent has context from previous turns

# ... time passes, container gets cleaned up ...

response3 = run_subagent(agent_run_id, "Summarize your findings", max_turns=200)
# Container restarted, continues with preserved transcript
```

**Prompt optimizer workflow (no conversation needed):**
```python
# Run critic with specific inputs (type_config as whole Pydantic model)
critic_agent_run_id = run_critic(
    definition_id="critic_abc123",
    type_config=CriticTypeConfig(
        snapshot_slug="ducktape/2025-01-15",
        scope_hash="abc123",
    ),
    max_turns=200,
)
# Returns agent_run_id - read results from issues table via SQL

# Run grader on that critic's output
grader_agent_run_id = run_grader(
    definition_id="grader",
    type_config=GraderTypeConfig(
        graded_agent_run_id=critic_agent_run_id,
    ),
    max_turns=200,
)
# Returns agent_run_id - read results from grader_evaluations table via SQL
```

**State Management:**
- Session identified by agent_run_id (no separate session concept)
- Conversation history persisted in events table
- No explicit end_agent needed - resources cleaned up when parent exits

**Persistence for restart:**

Everything needed to restart an agent after app quits must be saved to database:
- `agent_definition_id` - which definition to unpack
- `parent_agent_run_id` - shared across all agent types (for mount inheritance)
- Type-specific context in `type_config` JSONB:
  - Critics: `snapshot_slug`, `scope_hash`
  - Graders: `graded_agent_run_id`
  - Freeform/Prompt optimizer: just the type marker (metric-specific behavior in AGENT.md)
- Transcript events in `events` table (reconstruct conversation)

**Workspace persistence:**

Agent workspaces are stored at a predictable path derived from agent_run_id:
`~/.local/share/adgn/workspaces/{agent_run_id}/`

This directory:
- Is mounted as `/workspace` in the container
- Survives container restarts and app quits
- Contains the unpacked agent definition (AGENT.md, init, tools/, etc.)
- Can store files the agent creates during operation
- Never deleted by agent runtime code (cleanup is external, e.g., CLI gc command)

Agents can rely on `/workspace` being persistent. Any files created there
(notes, intermediate results, cached data) will survive restarts.

On restart:
1. Query `agent_runs` for agent's configuration
2. Workspace already exists at `~/.local/share/adgn/workspaces/{agent_run_id}/`
3. Reconstruct mounts from stored configuration
4. Rebuild `Agent` from persisted events
5. Restart container (workspace already mounted)
6. Continue conversation

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
    graded_agent_run_id: UUID  # Must be a critic run (validated)


class FreeformTypeConfig(BaseModel):
    """Freeform sub-agent configuration (no extra fields, just type marker)."""
    agent_type: Literal[AgentType.FREEFORM] = AgentType.FREEFORM


class TargetMetric(StrEnum):
    """Prompt optimizer target metric mode."""
    WHOLE_REPO = "whole-repo"  # Black-box validation: only full-snapshot examples
    TARGETED = "targeted"      # Allows per-file iteration on VALID split


class PromptOptimizerTypeConfig(BaseModel):
    """Prompt optimizer configuration.

    The target_metric controls validation split access:
    - WHOLE_REPO: TRAIN ground truth only, VALID metrics via SECURITY DEFINER function
                  (full-snapshot aggregates only)
    - TARGETED: TRAIN ground truth + VALID examples table (filenames only, no ground truth),
                VALID metrics via SECURITY DEFINER function (includes per-file aggregates)

    Both modes use SECURITY DEFINER functions for VALID metrics because:
    - Ground truth tables have TRAIN-only RLS
    - Aggregate views join ground truth tables, so inherit TRAIN-only restriction
    - Only SECURITY DEFINER can bypass RLS to compute VALID aggregates

    RLS uses current_prompt_optimizer_target_metric() to gate direct data access.
    """
    agent_type: Literal[AgentType.PROMPT_OPTIMIZER] = AgentType.PROMPT_OPTIMIZER
    target_metric: TargetMetric


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
    model: str                          # Model to use (e.g., "claude-sonnet-4-20250514")
    parent_agent_run_id: UUID | None   # FK to agent_runs, explicit None or UUID
    type_config: TypeConfig             # Pydantic model, stored as JSONB

    @property
    def agent_type(self) -> AgentType:
        return self.type_config.agent_type


class AgentRegistry:
    """Manages long-running agent containers.

    Two execution patterns supported:
    1. run_to_completion() - for critics/graders that run without user messages
    2. run_agent() - for conversational sub-agents that exchange messages

    Note: Handlers are set at agent creation. You cannot mix patterns on one agent.
    A critic (created with FinishOnAgentComplete handler) cannot later use run_agent().
    A freeform sub-agent (created with CaptureTextHandler) cannot use run_to_completion().
    """

    def __init__(self):
        self._agents: dict[UUID, AgentHandle] = {}

    async def create_agent(
        self,
        config: AgentConfig,
    ) -> UUID:
        agent_run_id = uuid4()

        # Create agent_runs record (persists all config for restart)
        create_agent_run(agent_run_id=agent_run_id, config=config)

        # Start container + MCP server (long-running)
        handle = await AgentHandle.create(
            agent_run_id=agent_run_id,
            config=config,
        )

        self._agents[agent_run_id] = handle
        return agent_run_id

    async def ensure_agent(self, agent_run_id: UUID) -> AgentHandle:
        """Get agent handle, restoring from database if needed (app restart)."""
        handle = self._agents.get(agent_run_id)
        if handle is None:
            handle = await self._restore_agent(agent_run_id)
            self._agents[agent_run_id] = handle
        return handle

    async def run_to_completion(self, agent_run_id: UUID, max_turns: int) -> None:
        """Run agent without user message until it finishes (or max_turns).

        For critics/graders that just need system prompt + bootstrap.
        Agent finishes when it produces final output (or hits max_turns).
        """
        handle = await self.ensure_agent(agent_run_id)
        await handle.run_to_completion(max_turns=max_turns)

    async def run_agent(self, agent_run_id: UUID, message: str, max_turns: int) -> str:
        """Send message and run until text response. For conversational use."""
        handle = await self.ensure_agent(agent_run_id)
        return await handle.run(message, max_turns=max_turns)

    async def _restore_agent(self, agent_run_id: UUID) -> AgentHandle:
        """Restore agent state from database after app restart."""
        run = get_agent_run(agent_run_id)
        if run is None:
            raise ValueError(f"No agent with agent_run_id {agent_run_id}")

        # Reconstruct config from database
        config = AgentConfig(
            definition_id=run.agent_definition_id,
            model=run.model,
            parent_agent_run_id=run.parent_agent_run_id,
            type_config=run.type_config,  # Pydantic model from JSONB
        )

        # Create handle (unpacks definition, starts container)
        handle = await AgentHandle.create(
            agent_run_id=agent_run_id,
            config=config,
        )

        # Restore conversation history from events table
        events = get_events_for_transcript(agent_run_id)
        handle.agent.restore_from_events(events)

        return handle

    async def stop_agent(self, agent_run_id: UUID):
        """Stop a specific agent's container (preserves workspace)."""
        handle = self._agents.pop(agent_run_id, None)
        if handle:
            await handle.shutdown()

    async def stop_all(self):
        """Stop all agent containers (e.g., on process exit). Preserves workspaces."""
        for handle in self._agents.values():
            await handle.shutdown()
        self._agents.clear()


@dataclass
class AgentHandle:
    """Handle to a single long-running agent.

    State held per agent:
    - agent_run_id: unique identifier, also PK in agent_runs table
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

    agent_run_id: UUID
    agent: Agent                      # Agent instance (owns transcript)
    compositor: PropertiesDockerCompositorHTTP  # Container + MCP lifecycle
    text_capture_handler: CaptureTextHandler  # Captures text + aborts
    config: AgentConfig               # For restart
    workspace: Path                   # Persistent workspace (host path, mounted as /workspace in container)
                                      # Path is deterministic: ~/.local/share/adgn/workspaces/{agent_run_id}/
    _lock: asyncio.Lock               # Prevent concurrent run() calls

    @classmethod
    async def create(
        cls,
        agent_run_id: UUID,
        config: AgentConfig,
        model_client: OpenAIModelProto,
    ) -> "AgentHandle":
        # 1. Load definition from DB
        definition = load_definition(config.definition_id)

        # 2. Unpack to persistent workspace (survives container restarts)
        workspace_mgr = WorkspaceManager.from_env()
        workspace = workspace_mgr.get_path(agent_run_id)
        if not workspace.exists():
            workspace.mkdir(parents=True)
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
        db_handler = DatabaseEventHandler(agent_run_id=agent_run_id)
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
            agent_run_id=agent_run_id,
            agent=agent,
            compositor=compositor,
            text_capture_handler=text_capture,
            config=config,
            workspace=workspace,
            _lock=asyncio.Lock(),
        )

    async def run(self, message: str, max_turns: int) -> str:
        """Send message and run agent until it produces text response.

        For conversational sub-agents (freeform). Uses CaptureTextHandler.
        Thread-safe: only one run() call can execute at a time.
        """
        async with self._lock:
            # Check if container died, restart if needed
            if not self.compositor.container.is_alive():
                await self.restart_container()

            # Add user message to agent's transcript
            self.agent.insert_message(UserMessage.text(message))

            # Run agent loop - CaptureTextHandler captures and aborts on text
            await self.agent.run(max_turns=max_turns)
            return self.text_capture_handler.take()  # Returns captured text, clears state

    async def run_to_completion(self, max_turns: int) -> None:
        """Run agent without user message until it finishes.

        For critics/graders that just need system prompt + bootstrap.
        Uses FinishOnAgentComplete handler (not CaptureTextHandler).
        Thread-safe: only one run() call can execute at a time.
        """
        async with self._lock:
            # Check if container died, restart if needed
            if not self.compositor.container.is_alive():
                await self.restart_container()

            # No user message - just run the agent loop
            await self.agent.run(max_turns=max_turns)

    async def restart_container(self):
        """Restart container after it was killed.

        Workspace is persistent - if it's missing, that's a fatal error.
        """
        if not self.workspace.exists():
            raise RuntimeError(
                f"Workspace {self.workspace} disappeared for agent {self.agent_run_id}. "
                "Cannot recover - agent state is corrupted."
            )

        # Restart container (workspace is persistent, already mounted)
        await self.compositor.runtime.server.start()

    async def shutdown(self):
        """Stop container but preserve workspace.

        Workspace is persistent and will remain for future restarts.
        Workspace cleanup is handled externally (e.g., CLI gc command, manual deletion).
        """
        await self.compositor.__aexit__(None, None, None)
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
    parent_agent_run_id=optimizer_agent_run_id,  # Spawned by optimizer
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
    parent_agent_run_id=current_agent_run_id(),  # Inherits snapshot mount
    type_config=FreeformTypeConfig(),
))
response = await registry.run_agent(sub_id, "Trace the auth flow...")

# CLI running grader (top-level, no parent)
registry = AgentRegistry()
agent_id = await registry.create_agent(AgentConfig(
    definition_id="grader",
    parent_agent_run_id=None,  # Top-level invocation from CLI
    type_config=GraderTypeConfig(
        graded_agent_run_id=some_critic_transcript,
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
