# Agent Definitions

## Overview

Agent definitions are self-contained directories that fully specify an agent's behavior:
prompt, bootstrap logic, and supporting tools/scripts. They are stored in PostgreSQL
as tar archives with database-level access control.

**Identity model:**
- **Repo-backed definitions**: Human-readable IDs (e.g., "critic", "grader"). Synced
  from `agent_defs/` directory, always updated in place on sync.
- **Agent-created definitions**: UUIDs assigned by the MCP server (via CLI helper).
  Immutable once created.

## Directory Structure

Agent definitions in `src/adgn/props/agent_defs/`:

```
agent_defs/
├── common/                      # Shared files (symlinked by agents)
│   ├── docs/                    # postgres_access.md, rls_mechanism.md, ...
│   └── init_helpers.py
├── critic/                      # AGENT.md, init, bin/, docs -> common, examples/
├── grader/                      # AGENT.md, init, bin/, docs -> common
├── clustering/                  # AGENT.md, init, bin/, docs/, examples/
├── prompt_optimizer/            # AGENT.md, init, bin/, docs/, examples/
├── improvement/                 # AGENT.md, init, bin/, docs -> common
└── <detector>/                  # Critic-based (inherits via symlinks: init, bin, docs -> critic)
```

**Conventions:**
- Each agent has `AGENT.md` (system prompt), `init` (bootstrap script), `bin/` (CLI)
- `docs/` can be a symlink (`-> ../common/docs`) or contain agent-specific docs
- Critic-based detectors inherit via symlinks to `../critic/`
- See `agent_defs/CLAUDE.md` for link style conventions

## Agent Types

```python
class AgentType(StrEnum):
    CRITIC = "critic"
    GRADER = "grader"
    PROMPT_OPTIMIZER = "prompt_optimizer"
    CLUSTERING = "clustering"
    IMPROVEMENT = "improvement"
    FREEFORM = "freeform"  # For sub-agents spawned by other agents
```

## Database Schema

**Tables:**
- `agent_definitions` - Archives with `id`, `agent_type`, `archive` bytea
- `agent_runs` - Unified runs with `agent_run_id`, `type_config` JSONB
- `events` - Tool call traces linked via `agent_run_id`
- `reported_issues`, `reported_issue_occurrences` - Critic output
- `grading_decisions` - Grader output

**Migrations:** All squashed into `20251223000000_schema_squashed.py`

## Access Control

All agents use a single `agent_base` role with RLS policies based on agent type:

- Username format: `agent_{agent_run_id}`
- Helper functions: `current_agent_run_id()`, `current_agent_type()` (SECURITY DEFINER)

| Resource | Critic | Grader | Prompt Optimizer |
|----------|--------|--------|------------------|
| Own events | SELECT | SELECT | SELECT (TRAIN only) |
| reported_issues | INSERT own | SELECT graded | SELECT TRAIN only |
| Ground truth | - | SELECT graded snapshot | SELECT TRAIN only |
| grading_decisions | - | INSERT own | SELECT TRAIN only |

## Runtime Flow

**CRITICAL: Workspace must be created BEFORE Docker container starts.**

```
1. Create AgentRun in database
2. Get workspace path: workspace_manager.get_path(agent_run_id)
3. ensure_definition_unpacked(definition_id, workspace_path)
4. Enter AgentEnvironment context (starts container with mount)
5. Create AgentHandle (loads AGENT.md, builds bootstrap)
6. Run agent loop
```

**Environment variables available to agents:**
- Database: `$PGHOST`, `$PGPORT`, `$PGUSER`, `$PGPASSWORD`, `$PGDATABASE`
- MCP: `$MCP_SERVER_URL`, `$MCP_SERVER_TOKEN`
- `$AGENT_RUN_ID` - UUID of the current agent run

## Agent CLI Commands

| Agent | Script | Subcommands |
|-------|--------|-------------|
| Critic | `critique.py` | `insert-issue`, `insert-occurrence`, `submit`, `list-issues`, `delete-issue` |
| Grader | `grader.py` | `add-tp-match`, `add-fp-match`, `add-no-match`, `delete-decision`, `submit` |
| Clustering | `clustering.py` | `create-cluster`, `assign-to-cluster`, `assign-to-tp`, `assign-to-fp` |
| Prompt Optimizer | `optimizer.py` | `create-critic-definition`, `run-critic`, `run-grader` |

Usage: `python /workspace/bin/<script>.py <command> [args]`

## Future Work

### Sub-Agent Spawning (FREEFORM type)

Agents can spawn sub-agents for task decomposition. A critic might delegate
specialized analysis to sub-agents.

- Sub-agent gets own `agent_run_id` with `parent_agent_run_id` pointing to parent
- Inherits snapshot mount from parent
- Container can be restarted; transcript reconstructed from events table

### Recursive Cost Aggregation

Track costs across agent sub-trees:
- `own_cost` - Cost of this agent run only
- `cost_including_subagents` - Recursive sum including descendants

### Dissolve agent_queries.py

Refactor SQL template queries from `db/agent_queries.py` into agent-specific
CLI commands under `agent_defs/*/bin/`.

## References

- Agent definitions: `src/adgn/props/agent_defs/`
- AgentHandle: `src/adgn/props/agent_handle.py`
- AgentRegistry: `src/adgn/props/agent_registry.py`
- TempUserManager: `src/adgn/props/db/temp_user_manager.py`
- E2E tests: `tests/props/critic/test_e2e.py`, `tests/props/grader/test_e2e.py`
