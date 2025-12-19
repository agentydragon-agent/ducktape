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

### Database Schema

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

## Agent Access Pattern

Agents do NOT get definitions auto-mounted. Instead, they use a helper to inflate
definitions from the database into their workspace:

### Python Helper

```python
from adgn.props.agent_helpers import inflate_agent_definition

# Inflate a specific definition by ID
inflate_agent_definition(agent_id=47, target_dir=Path("/workspace/agents/critic/47"))

# Inflate the baseline critic definition
inflate_agent_definition(agent_type="critic", baseline=True, target_dir=Path("/workspace/agents/critic/base"))

# Inflate own definition (uses environment variable set by runtime)
inflate_agent_definition(self=True, target_dir=Path("/workspace/agents/self"))
```

### CLI

```bash
# Inflate by ID
inflate-agent 47 /workspace/agents/critic/47

# Inflate baseline
inflate-agent --type critic --baseline /workspace/agents/critic/base

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
   - Its own definition at /agents/self/
   - Critic definition IDs it can read (via RLS)

2. Optimizer inflates current best critic:
   $ inflate-agent 47 /workspace/agents/critic/47

3. Optimizer reads and analyzes:
   - /workspace/agents/critic/47/AGENT.md
   - /workspace/agents/critic/47/tools/...

4. Optimizer creates modified version:
   $ cp -r /workspace/agents/critic/47 /workspace/agents/critic/new
   $ edit /workspace/agents/critic/new/AGENT.md
   $ edit /workspace/agents/critic/new/tools/analyze.py

5. Optimizer saves new definition:
   $ save-agent-definition --type critic --parent 47 /workspace/agents/critic/new
   # Returns: Created agent definition ID 48

6. Optimizer runs critic with new definition:
   $ run-critic --definition 48 --snapshot ducktape/2025-01-15
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
