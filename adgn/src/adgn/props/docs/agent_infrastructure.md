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
│   ├── helpers.py               # upsert_prompt, run_critic, run_grader
│   ├── cli_helpers.py           # CLI: upsert-prompt, run-critic, run-grader
│   └── examples/                # Optimizer-specific examples
│       ├── listing.py           # List examples/snapshots by split/scope
│       ├── prompt_metrics_targeted.py   # Metrics via views (targeted mode)
│       ├── prompt_metrics_whole_repo.py # Metrics via SECURITY DEFINER (whole-repo mode)
│       ├── runs.py              # Run status, execution traces, failure analysis
│       ├── pareto.py            # Pareto frontier analysis
│       └── evaluation_pipeline.py       # Async run_critic/run_grader usage
├── clustering/
│   ├── helpers.py               # clustering helpers
│   ├── cli_helpers.py           # CLI: create-cluster, assign-unknown, submit
│   └── examples/                # Clustering-specific examples
├── examples/                    # Shared examples (used by multiple agents)
│   ├── working_with_examples.py
│   └── mcp_http_client_example.py
└── cli/
    └── cmd_agent_helper.py      # Top-level agent-helper group
```

## Adding New Helpers

### Pattern: Python + CLI

1. **Add async helper** in `<agent>/helpers.py`:
   ```python
   async def insert_issue(
       session: AsyncSession,
       critic_run_id: UUID,
       issue_id: str,
       rationale: str,
   ) -> ReportedIssue:
       """Insert a reported issue for the current critic run."""
       issue = ReportedIssue(
           critic_run_id=critic_run_id,
           issue_id=issue_id,
           rationale=rationale,
       )
       session.add(issue)
       await session.commit()
       return issue
   ```

2. **Add CLI command** in `<agent>/cli_helpers.py`:
   ```python
   import typer
   from adgn.props.critic.helpers import insert_issue
   from adgn.props.agent_helpers import get_critic_run_id, get_async_session

   app = typer.Typer()

   @app.command("add-issue")
   def add_issue(
       issue_id: str,
       rationale: str,
       critic_run_id: Annotated[UUID | None, typer.Option()] = None,
   ) -> None:
       """Add an issue to the current critic run."""
       run_id = critic_run_id or get_critic_run_id()  # Auto-infer from env
       async def _run():
           async with get_async_session() as session:
               await insert_issue(session, run_id, issue_id, rationale)
       asyncio.run(_run())
       print(f"Added issue {issue_id}")
   ```

3. **Register in CLI** in `cli/cmd_agent_helper.py`:
   ```python
   from adgn.props.critic.cli_helpers import app as critic_app
   app.add_typer(critic_app, name="critic")
   ```

### Auto-Inference Pattern

Helpers auto-detect context from environment when run by agent:

```python
def get_critic_run_id() -> UUID:
    """Get critic run ID from environment."""
    env_value = os.environ.get("CRITIC_RUN_ID")
    if not env_value:
        raise ValueError("CRITIC_RUN_ID not set - run via agent or pass --critic-run-id")
    return UUID(env_value)
```

CLI arguments override auto-detected values for manual testing/debugging.

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
- Uses views directly (`occurrence_credits`, `aggregated_recall_by_prompt`)
- Can see validation example filenames
- Example: `prompt_metrics_targeted.py`

### Whole-Repo Mode
- Uses `get_validation_run_aggregates()` SECURITY DEFINER function
- Validation examples RLS-blocked
- Example: `prompt_metrics_whole_repo.py`

Keep mode-specific examples separate - don't try to unify incompatible data access patterns.
