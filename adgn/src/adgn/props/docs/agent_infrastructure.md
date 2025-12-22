# Agent Infrastructure Strategy

This document describes the unified infrastructure for all props agents (Critic, Grader, Prompt Optimizer, Prompt Improver, Clustering).

## Core Principles

### 1. Agents Are Power Users

Agents interact with the system via CLI, Python, and raw SQL. The infrastructure:
- Documents schema publicly via ORM docstrings and SQL comments
- Controls data access via RLS (different agents see different data)
- Avoids duplication between prompts, example files, and docstrings
- Keeps agent-specific content under agent-specific directories

### 2. Single Implementation, Multiple Interfaces

Query logic, helpers, and CLI commands share implementation:
- Python helpers (async) are the single source of truth
- CLI commands wrap helpers with `asyncio.run()`
- Example scripts import from helpers (no duplication)

### 3. Layered Bootstrap

Agents receive context in layers:
- **Layer 0:** Environment (MCP resources, `PG*` vars)
- **Layer 1:** Common foundation (`db/models.py`, shared examples)
- **Layer 2:** Role-specific (`<agent>/examples/*.py`, agent-specific helpers)

## Database Access

Database access is automatic - just use `get_session()`:

```python
from adgn.props.db import get_session
from adgn.props.db.models import Snapshot

# Database auto-initializes on first use from PG* env vars
with get_session() as session:
    snapshots = session.query(Snapshot).all()
```

Key points:
- **Auto-initialization:** `get_session()` auto-initializes from `PG*` env vars on first call
- **Thread-safe:** Uses double-checked locking for safe concurrent initialization
- **No explicit setup:** Just call `get_session()` - database connection is established automatically

For tests that need explicit control:
```python
from adgn.props.db import dispose_db, init_db

dispose_db()           # Reset state
init_db(test_config)   # Initialize with specific config
```

## Directory Structure

```
src/adgn/props/
├── agent_helpers.py             # Shared: mcp_client_from_env
├── critic/
│   ├── helpers.py               # insert_issue, insert_occurrence, submit_critique
│   ├── cli_helpers.py           # CLI: add-issue, add-occurrence, submit
│   └── examples/                # Critic-specific examples (if any)
├── grader/
│   ├── helpers.py               # grader helpers
│   ├── cli_helpers.py           # CLI: add-decision, delete-decision, submit
│   └── examples/                # Grader-specific examples (if any)
├── prompt_optimize/
│   ├── helpers.py               # run_critic, run_grader
│   ├── cli_helpers.py           # CLI: run-critic, run-grader
│   └── examples/                # Optimizer-specific examples
│       ├── listing.py           # List examples/snapshots by split/scope
│       ├── definition_stats_targeted.py   # Definition stats via views (targeted mode)
│       ├── definition_stats_whole_repo.py # Definition stats via SECURITY DEFINER (whole-repo mode)
│       ├── pareto.py            # Pareto frontier analysis
│       └── evaluation_pipeline.py       # Async run_critic/run_grader usage
├── clustering/
│   ├── helpers.py               # clustering helpers
│   ├── cli_helpers.py           # CLI: create-cluster, assign-unknown, submit
│   └── examples/                # Clustering-specific examples
├── examples/                    # Shared examples (used by multiple agents)
│   ├── working_with_examples.py
│   ├── runs.py                  # Run status, execution traces, failure analysis
│   └── mcp_http_client_example.py
└── cli/
    └── cmd_agent_helper.py      # Top-level agent-helper group
```

## Adding New Helpers

### Helper Functions

Agent-specific helpers live in `agent_defs/<agent>/helpers.py`. These are sync functions that auto-detect agent run context from PostgreSQL RLS.

Example (critic helpers):
```python
from adgn.props.agent_defs.critic.helpers import insert_issue, insert_occurrence

insert_issue("dead-code-1", "Unused function found")
insert_occurrence("dead-code-1", "utils.py", 10, 20)
```

The agent run ID is extracted from the PostgreSQL username pattern (`agent_{uuid}`):
```python
from adgn.props.agent_helpers import get_current_agent_run_id

with get_session() as session:
    agent_run_id = get_current_agent_run_id(session)
```

## Adding Bootstrap Content

### Registry Pattern

Bootstrap items are registered per agent type:

```python
# In <agent>/bootstrap.py
from adgn.props.bootstrap import BootstrapRegistry

def register_critic_bootstrap(registry: BootstrapRegistry) -> None:
    """Register critic-specific bootstrap items."""
    registry.add_file("db/models.py")
    registry.add_file("critic/helpers.py")
    registry.add_resource("snapshot://current/slug")
    registry.add_resource("scope://current/files")
```

### Recipes

Recipes compose bootstrap items for specific agent configurations:

```python
def critic_bootstrap_recipe(snapshot_slug: str, scope: Scope) -> list[BootstrapItem]:
    """Build bootstrap for critic agent."""
    return [
        FileContent("db/models.py"),
        ResourceContent("snapshot://current/slug", snapshot_slug),
        ResourceContent("scope://current/files", scope.to_json()),
        FileContent("critic/helpers.py"),
    ]
```

## Design Decisions

### ORM Objects (Not DTOs)

Helpers return ORM objects, not dataclasses/DTOs:
- More flexible for agents who traverse relationships
- Avoids maintenance burden of parallel DTO hierarchies
- Session management handled by callers

### Async Core + Sync CLI Wrapper

- Core helpers are async (matches MCP server patterns)
- Typer commands wrap via `asyncio.run()` for CLI use
- No separate sync implementation to maintain

### Full models.py in Bootstrap

All agents see the complete `db/models.py`:
- Single source of truth (no separate schema docs)
- Agents can write custom queries with full schema knowledge
- Trade-off: More context tokens, but better query accuracy

### Agent-Specific Content Under Agent Directories

Keep related code together:
- `critic/helpers.py` + `critic/cli_helpers.py` + `critic/examples/`
- Easier to find and maintain
- Clear ownership boundaries

## Testing Requirements

### Bootstrap Tests

```python
def test_critic_bootstrap_includes_models(synced_test_fixtures):
    """Critic bootstrap should include db/models.py."""
    items = critic_bootstrap_recipe(
        snapshot_slug="test-fixtures/test-trivial",
        scope=AllFilesScope(),
    )
    assert any("db/models.py" in item.path for item in items)
```

### Example Script Tests

All example scripts must:
1. Import from helpers (not duplicate logic)
2. Work with zero configuration (auto-detect from environment)
3. Have tests verifying they run correctly

```python
def test_listing_example_runs(synced_test_fixtures):
    """listing.py should run without errors."""
    from adgn.props.prompt_optimize.examples import listing
    # Example runs during import or has main() that can be called
```

## Mode-Specific Examples

Prompt optimizer has two modes affecting data access:

### Targeted Mode
- Uses views directly (`occurrence_credits`, `aggregated_recall_by_definition`)
- Can see validation example filenames
- Example: `definition_stats_targeted.py`

### Whole-Repo Mode
- Uses SQL: `SELECT * FROM get_validation_run_aggregates()` (PostgreSQL SECURITY DEFINER function, NOT Python)
- Validation examples RLS-blocked
- Example: `definition_stats_whole_repo.py`

Keep mode-specific examples separate - don't try to unify incompatible data access patterns.
