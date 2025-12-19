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
├── bootstrap.sh          # Runs on agent startup (optional)
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
Run `./bootstrap.sh` for environment details and available tools.
(Note: Runtime auto-executes this, but instruction remains for clarity)

## Workflow
1. Analyze code using available tools (rg, ruff, mypy, etc.)
2. Report issues using Python helpers or direct SQL
3. Complete review by calling submit_critique()

... (rest of agent-specific instructions)
```

### bootstrap.sh

If present, executed automatically by the runtime before agent sampling begins
(warm-start pattern - we don't rely on LLM following an instruction to run it).

Default bootstrap.sh for repo-tracked agents reads common boilerplate from the
installed adgn package:

```bash
#!/bin/bash
# Bootstrap script for critic agent

# Read MCP connection info from adgn package resources
python3 -c "
from importlib.resources import files
print(files('adgn.props.prompts').joinpath('mcp_http_connection.md').read_text())
"

# Read scope from environment (set by runtime)
echo "=== Review Scope ==="
echo "Snapshot: $SNAPSHOT_SLUG"
echo "Files: $SCOPE_FILES"

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
    id SERIAL PRIMARY KEY,
    agent_type TEXT NOT NULL,              -- 'critic', 'grader', 'prompt_optimizer', etc.
    definition_sha256 TEXT NOT NULL,       -- SHA256 of uncompressed content (for dedup)
    archive BYTEA NOT NULL,                -- gzip-compressed tar archive
    parent_id INTEGER REFERENCES agent_definitions(id),  -- lineage tracking
    created_at TIMESTAMPTZ DEFAULT now(),

    -- Provenance
    prompt_optimization_run_id UUID REFERENCES prompt_optimization_runs(id),

    UNIQUE(definition_sha256)              -- content-addressed deduplication
);

-- Index for finding latest variants of a type
CREATE INDEX idx_agent_definitions_type_id ON agent_definitions(agent_type, id DESC);
```

### Content Addressing

The `definition_sha256` is computed from a deterministic serialization:

```python
def compute_definition_hash(definition_dir: Path) -> str:
    """Compute SHA256 of agent definition directory.

    Process:
    1. List all files recursively, sorted by path
    2. For each file: hash(relative_path + file_mode + file_content)
    3. Hash the concatenation of all file hashes
    """
    hasher = hashlib.sha256()
    for path in sorted(definition_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(definition_dir)
            mode = "x" if os.access(path, os.X_OK) else "r"
            hasher.update(f"{rel}:{mode}:".encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()
```

Identical definitions (by content) share the same `definition_sha256`, enabling
deduplication and fast equality checks.

## Access Control

### RLS Policies

Agent definitions use the same RLS pattern as other props tables. Example policy
for prompt optimizer accessing critic definitions:

```sql
-- Prompt optimizer can read critic definitions from its optimization run
CREATE POLICY optimizer_read_critic ON agent_definitions
    FOR SELECT
    USING (
        agent_type = 'critic'
        AND prompt_optimization_run_id = current_optimization_run_id()
    );

-- Prompt optimizer can insert new critic definitions
CREATE POLICY optimizer_insert_critic ON agent_definitions
    FOR INSERT
    WITH CHECK (
        agent_type = 'critic'
        AND prompt_optimization_run_id = current_optimization_run_id()
    );
```

### Baseline Definitions

Canonical repo-tracked definitions (the "base" versions) are inserted with
`prompt_optimization_run_id = NULL` and readable by all agents that need them.

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
3. Executes `bootstrap.sh` via docker_exec (if present)
4. Injects bootstrap output as first assistant message (warm-start)
5. Reads `/workspace/AGENT.md` as system prompt
6. Begins agent sampling

This warm-start pattern ensures the agent sees bootstrap output without relying
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
- Track lineage via `parent_id`
- Metrics queries that group by definition

## Runtime Information (No Jinja2)

Agent definitions are fully static - no Jinja2 templating.

### How dynamic info is provided

1. **Common boilerplate** (MCP connection docs, tool usage patterns):
   - Stored in `adgn.props.prompts` package resources
   - bootstrap.sh reads via `importlib.resources`
   - Shared across all agents, versioned with the adgn package

2. **Run-specific context** (snapshot slug, file scope, credentials):
   - Passed via environment variables (`$SNAPSHOT_SLUG`, `$SCOPE_FILES`, `$PGHOST`, etc.)
   - bootstrap.sh prints these for the agent to see

3. **MCP server URL/token**:
   - `$MCP_SERVER_URL` and `$MCP_SERVER_TOKEN` set by runtime
   - bootstrap.sh demonstrates connection (already the pattern today)

This keeps AGENT.md fully self-contained while allowing runtime-specific context.

### Bootstrap output limits

The bootstrap.sh output is injected into the conversation as the first assistant
turn (warm-start). To prevent truncation:

- docker_exec tool supports configurable `max_output_chars` parameter
- Default bootstrap calls use higher limits (e.g., 50KB)
- E2E tests verify bootstrap output is not truncated (check for TruncatedOutput model)

## Syncing Repo-Tracked Definitions

Canonical agent definitions live in git at `adgn/agent_definitions/`. A sync
command ensures they're present in the database:

```bash
# Sync all repo-tracked definitions to database
python -m adgn.props.cli sync-agent-definitions

# This:
# 1. Walks adgn/agent_definitions/
# 2. For each directory, computes SHA256
# 3. Upserts to database if not present (idempotent)
```

The sync command runs:
- On CI after merge to main
- Manually when developing new base definitions
- Optionally as part of `run_critic` startup (auto-sync baseline if missing)

## Size Limits

- **Folder size**: Soft limit ~1MB (enforced by CLI tooling)
- **Database column**: 2MB limit on `archive` column (hard limit)
- **Validation**: Happens at agent start time, not insert time (simpler)

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
├── bootstrap.sh          # Auto-executed on startup
└── tools/                # Agent's helper scripts (if any)
```

Agent reads its prompt from `/workspace/AGENT.md`. Simple, no symlinks needed.
Runtime context comes via environment variables, not files.
