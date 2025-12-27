# Guide for agents working on `props` package

## Specimens Dataset Location

**Specimens data lives in a separate repository**: [github.com/agentydragon/specimens](https://github.com/agentydragon/specimens)

The `ADGN_PROPS_SPECIMENS_ROOT` environment variable points to the specimens repo (typically `~/code/specimens`). The props package loads specimen data from this external location.

## Key Documentation

**Agent-facing documentation (SSOT - transcluded below):**

@src/props/docs/db/ground_truth.md.j2
@src/props/docs/db/examples.md.j2
@src/props/docs/db/evaluation_flow.md.j2
@src/props/docs/database_access.md
@src/props/docs/writing_agent_definitions.md.j2

**Developer documentation (implementation notes):**
- `docs/training_strategy.md` — Implementation files for training pipeline
- `docs/agent_infrastructure.md` — Directory structure, testing requirements
- `README.md` — Package overview, conventions, workflow

**Specimen authoring (in specimens repo):**
- Specimens repository has its own CLAUDE.md with format specs, authoring guide, and quality checklist

## Documentation Guidelines

@src/props/docs/AGENTS.md

## MCP Wiring & Prompt Authoring

### What the agent already sees automatically
- The Agent prepends an MCP "wiring banner" to the system message before sampling (see `src/adgn/agent/agent.py`: `_build_effective_instructions`).
- The banner is computed from a live MCP snapshot: running server names, their tool names/descriptions, and a short list of resources (URIs) per server.
- For the Docker exec server, the `container.info` resource includes image tag/ID, image build history (e.g., `pip install ... ruff==…`), mounted volumes (e.g., `/workspace`), working directory, and network mode.
- The banner lists only a few resources per server for readability; the agent can call `resources/list`/`resources/read` to enumerate/read more.

### Implications for runbooks/prompts (do vs don't)
- Do:
  - Describe the analysis strategy and sequencing (what to check, in what order, why).
  - Provide concrete command examples (e.g., run Ruff/Mypy/Vulture/custom detectors) and define the required final outputs (inline JSON/markdown with truncation rules).
- Don't (redundant due to wiring/banner):
  - Re‑enumerate MCP servers, tool schemas, or resource URIs shown in the banner.
  - Restate tool versions/pins or platform details; the agent can read them from `container.info`.
  - Repeat wiring details like server names, volumes (`/workspace`), or cache/temp env; these are implied by the container wiring.
  - Restate long acceptance criteria verbatim; link to property docs or summarize briefly.

## Tooling Specifics (Current Image)
- Ruff: run `ruff check --output-format json /workspace`; set `XDG_CACHE_HOME=/tmp` (or `RUFF_CACHE_DIR=/tmp/.ruff_cache`).
- Mypy (preferred): run the CLI with the repo config if present, e.g., `mypy --config-file pyproject.toml /workspace` (add `--strict` if appropriate).
- Vulture: pinned to `2.14`. You may use the CLI (`vulture /workspace --min-confidence 60 --sort-by-size`) or Python API as needed.
- Custom detectors: `adgn-detectors-custom --root /workspace --out /tmp/custom-findings.json`.
- Duplication hotspots: `jscpd --path /workspace --reporters json` (or restrict via `--languages python`, honor `.gitignore` if applicable).

## Unified Runner (CLI)
- Preferred command: `props run`
  - Scope (choose one): `--snapshot <slug>` or `--path /path/to/code`
  - Prompt source (choose one): `--preset <name>` or `--prompt-file /path/to/runbook.j2.md` or `--prompt-text 'inline'`
  - Mode:
    - Freeform (default): emits plain final text
    - Structured: `--structured true` — attaches `critic_submit` and requires a final `submit(issues=N)`; compatible with graders
  - Always renders prompts via Jinja with standard props context; plain Markdown passes through unchanged.

Examples
- Structured, max‑recall critic on a specimen:
  - `props run --snapshot <slug> --structured true --preset max-recall-critic`
- Dead‑code runbook on a local path (structured):
  - `props run --preset dead-code-and-reachability --path /repo --structured true`
- Open review with a custom runbook (freeform):
  - `props run --prompt-file ./my_review.j2.md --path /repo`

## Wiring Defaults (Container)
- Network disabled; workspace mounted read‑only at `/workspace`.
- Caches/temp redirected to `/tmp` and Python pycache relocated to `/tmp/__pycache__`.
- Tool versions/pins are visible via the Docker `container.info` resource (image history shows the build lines).

## Docker Build
**Important:** Run all docker build commands from the workspace root (`ducktape/`), not from `adgn/`.
- Properties critic image lives under `docker/llm/properties-critic/Dockerfile`.
- Build locally: `docker build -f docker/llm/properties-critic/Dockerfile -t adgn-llm/properties-critic:latest .`

## Development Server Management (devenv + process-compose)

The backend, frontend, and PostgreSQL are managed by devenv via process-compose. **Never start these services manually.**

### Starting All Services
```bash
cd props
devenv up  # Starts postgres, backend, frontend
```

### Process Management Commands
```bash
# List processes and their status
process-compose process list

# Get detailed status of a process
process-compose process get backend

# View logs
process-compose process logs backend

# Restart a process (picks up code changes)
process-compose process restart backend

# Stop/start a process
process-compose process stop backend
process-compose process start backend
```

### Service URLs
- Backend: http://localhost:8000
- Frontend: http://localhost:5173
- PostgreSQL: localhost:5433

### What to NEVER Do
- **NEVER** run `uvicorn` manually
- **NEVER** run `pnpm dev` manually for the frontend
- **NEVER** start the postgres container manually
- **NEVER** kill service PIDs without checking if they're process-compose managed

Manual service starts will:
1. Block process-compose from starting (port conflict: "Address already in use")
2. Watch wrong directories (code changes won't reload)
3. Break the devenv-managed workflow

### Regenerating OpenAPI Schema
After backend API changes:
```bash
cd ../props_frontend
pnpm generate  # Requires backend running
```

### Backend Watch Directories
The devenv backend watches:
- `../props_backend/src` - Backend route handlers
- `src` - Props package

Changes trigger automatic reload.

## Database Migrations (Alembic)

**All schema changes must go through Alembic migrations.** Do not edit the database schema directly.

- **Migrations location:** `src/props/db/migrations/versions/`
- **Configuration:** `src/props/db/migrations/env.py` (reads database URL from environment via `get_production_config()`)
- **Alembic CLI:** Run from `src/props/db/` directory with `direnv exec . alembic <command>`

**Project conventions:**
- Use YYYYMMDD000000 timestamp format for revision IDs (e.g., `20251213000000`)
- ORM models in `db/*.py` are still required for application code
- RLS policies: managed in `src/props/db/setup.py` via `enable_rls()` (not in migrations)
- RLS helper functions: should be created in migrations (they're part of the schema)

**Fresh database setup (dev/test):**
```bash
props db recreate  # Drops schema, runs migrations, creates RLS/views
```

**CRITICAL - NEVER RECREATE WITHOUT PERMISSION:** The `props db recreate` command drops ALL data including expensively-collected agent rollouts. **NEVER run this command without the user's explicit verbal agreement.** For applying migrations to an existing database, use the standard Alembic workflow instead (see Infrastructure TODOs for current limitations).

**Example migration:** See `src/props/db/migrations/versions/20251213000000_add_clustering_tables.py`

**CASCADE WARNING:** When dropping views with CASCADE (e.g., `DROP VIEW IF EXISTS recall_by_run CASCADE`), all dependent views are also dropped. Before writing such a migration:
1. Query `pg_depend` or check the schema to list ALL dependent views
2. Recreate all dropped views in correct dependency order in the same migration
3. Re-grant permissions (`GRANT SELECT ON TABLE view_name TO agent_base`)

Example: `recall_by_run` has 4 dependent views that cascade:
- `recall_by_definition_example` → `recall_by_definition_split_kind`
- `recall_by_definition_example` → `recall_by_example`
- `recall_by_definition_example` → `pareto_frontier_by_example`

See `20251227000000_exclude_in_progress_from_recall.py` for a complete CASCADE-aware migration.

## Temporary Database Users (Scoped Access)

**Pattern:** Task-specific agents create temporary PostgreSQL users with RLS-scoped access for the duration of their execution.

**Why temporary users?**
- Enforces data isolation (e.g., TRAIN-only access for optimization agents)
- Prevents accidental leakage of validation/test data during training
- No persistent credentials to manage or rotate
- Automatic cleanup on agent exit

**Function-Based RLS:**
- Username pattern encodes scope (e.g., `prompt_optimizer_agent_{uuid}`)
- PostgreSQL function extracts ID from username: `current_prompt_optimizer_run_id()`
- Centralized policies use function to filter rows - O(1) overhead
- Scales to many concurrent users without per-user policy creation

**Example: Prompt Optimizer Agent**
- Creates temporary user: `prompt_optimizer_agent_{run_id}`
- RLS function: `current_prompt_optimizer_run_id()` extracts UUID from username
- RLS policies enforce anti-overfitting data isolation:
  - **TRAIN split**: Full access
    - Examples: All examples visible (per-file and whole-snapshot)
    - Ground truth: `true_positives`, `false_positives` tables readable
    - Individual runs: `agent_runs` (critic/grader via `type_config`), `reported_issues`, `grading_decisions` readable
    - Aggregate views: `recall_by_definition_split_kind`, `recall_by_example` for TRAIN
    - Agent can debug, inspect per-occurrence credits, iterate on specific failures
  - **VALID/TEST splits**: Restricted to prevent overfitting
    - Examples: Only whole-snapshot examples visible (per-file examples hidden)
    - Ground truth: `true_positives`, `false_positives` tables return 0 rows (RLS filtered)
    - Individual runs: `agent_runs`, `reported_issues`, `grading_decisions` hidden (RLS filtered)
    - Aggregate views: `recall_by_definition_split_kind`, `recall_by_example` show VALID/TEST metrics
    - Agent can run evaluations on whole snapshots, but only sees scalar recall metrics
    - Cannot inspect which issues were missed or iterate on specific VALID failures
- Container receives temp user credentials (not admin)
- Automatic cleanup on compositor exit

**Implementation:**
```python
from props.prompt_optimize.prompt_optimizer import PromptOptimizerAgentEnvironment

# AgentEnvironment pattern (like critic/grader):
agent_env = PromptOptimizerAgentEnvironment(
    workspace_root=workspace_path,
    docker_client=docker_client,
    optimizer_run_id=run_id,
    critic_client=critic_client,
    grader_client=grader_client,
    db_config=db_config,
    optimizer_state=PromptOptimizerState(),
    target_metric=TargetMetric.WHOLE_REPO,
    budget_limit=100.0,
)
async with agent_env as compositor:
    # Temp user created automatically
    # HTTP MCP server with prompt_eval tools running
    # Container has PG* env vars and MCP_SERVER_URL/TOKEN
    # Snapshots are fetched by init script, not pre-mounted
    ...
```

**Other examples:**
- Improvement agents: Use `TempUserManager` with `ImprovementTypeConfig` for RLS-scoped access to allowed examples

**See also:**
- `src/props/db/temp_user_manager.py` - Unified user manager for all agent types
- `src/props/db/migrations/versions/20251215000000_add_prompt_optimizer_rls.py` - RLS setup migration
- `src/props/db/migrations/versions/20251230000000_migrate_improvement_to_agent_runs.py` - Improvement agent RLS migration

## Accessing PostgreSQL Directly

Use Python with the database config module:

```python
from props.db.config import get_production_config
from sqlalchemy import create_engine, text

config = get_production_config()
engine = create_engine(config.admin_url())

with engine.connect() as conn:
    result = conn.execute(text('SELECT slug FROM snapshots ORDER BY slug'))
    for row in result:
        print(row[0])
```

**Key points:**
- Database connection parameters come from environment variables set by devenv:
  - Standard `PG*` vars for admin access (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE)
  - Custom `PROPS_DB_CONTAINER_NAME` for container routing
- Always run from within the props devenv shell (`direnv allow` or `direnv exec . <command>`)
- Tables are in the default `public` schema - direct queries work without qualification
- Temporary users with scoped access are created automatically by specific agents (e.g., prompt optimizer)

**psql access:**
```bash
# Connect with psql (uses PG* environment variables set by devenv)
direnv exec . psql

# Or from outside props/ (use path to props directory):
cd /path/to/ducktape/props && direnv exec . psql
```

## Architecture: MCP I/O Models vs DB Persistence Models

### Problem
Database persistence models should NOT use MCP I/O protocol types directly. Using MCP types (like `CriticSubmitPayload`, `ReportedIssue`, `GraderOutput`) in database schemas couples database migrations to protocol changes.

### Solution: Two Parallel Model Hierarchies

**MCP I/O Models** (in `critic/models.py`, `grader/models.py`):
- Purpose: Define the API contract for MCP tool inputs/outputs
- Characteristics:
  - Use NewType wrappers for type safety (`TruePositiveID`, `InputIssueID`)
  - Use rich types (`Path`, `set`, frozen models)
  - Include validation logic
  - May change as protocol evolves
- Examples: `CriticSubmitPayload`, `ReportedIssue`, `Occurrence`, `GraderOutput`

**DB Persistence Models** (in `db/snapshots.py`):
- Purpose: Define the database storage format
- Characteristics:
  - Use primitives: `str` instead of NewType, `list` instead of `set`
  - All `Path` objects stored as strings
  - All sets stored as lists
  - No complex validation (data already validated before storage)
  - Frozen models (`frozen=True`)
  - Stable schema independent of protocol changes
- Examples: `DBCriticSubmitPayload`, `DBReportedIssue`, `DBOccurrence`, `DBGraderOutput`

**Conversion Functions** (in `grader/persistence.py`):
- Purpose: Bridge between MCP and DB models
- Live in the application layer (grader), not the database layer
- Conversion patterns:
  - **TO DB (when writing)**: `grader_output_to_db()`
  - Only convert DB → MCP when you need MCP-specific behavior

### Usage Patterns

**When reading critic data from database:**
```python
# Use ORM directly - no conversion needed
from props.db.models import ReportedIssue

with get_session() as session:
    issues = session.query(ReportedIssue).filter_by(agent_run_id=critic_run_id).all()
    for issue in issues:
        print(issue.issue_id, issue.rationale)
        for occ in issue.occurrences:
            print(occ.locations)
```

**When reading grader data from database:**
```python
# Use DB model directly (inline field access)
grader_run = session.get(GraderRun, grader_run_id)
for result in grader_run.output.occurrence_results:
    # Access DB model fields directly
    tp_id = result.tp_id
    found_credit = result.found_credit
```

### Key Benefits
1. **Database independence**: Schema changes don't require protocol changes
2. **Type safety**: Full Pydantic validation on both sides
3. **Performance**: No unnecessary conversions when reading
4. **Clarity**: Explicit conversion at boundaries

### Layer Isolation Test
The test `tests/props/db/test_layer_isolation.py` enforces that the database layer (`db/`) does not import from MCP I/O layers (`critic.models`, `grader.models`). This prevents accidental coupling.

### Migration Guide
When you encounter code using MCP models in database operations:
1. Check if a `DB*` model exists in `db/snapshots.py` (e.g., `DBCriticSubmitPayload`)
2. If not, create the DB model hierarchy (all primitives, no NewTypes)
3. Create conversion functions in the appropriate persistence module
4. Update database ORM models to use DB types
5. Update code to convert TO DB when writing
6. Update code to use DB model directly when reading (inline access)
7. Only add DB → MCP conversion if truly needed for business logic

## Testing

**For comprehensive testing conventions and patterns, see:**

@tests/props/CLAUDE.md

Key principles:
- Git fixtures are the single source of truth (no synthetic ORM models)
- Use `synced_test_fixtures` pytest fixture for all test data
- Use factory functions (`make_critic_run`, `make_grader_run`) with required parameters
- Query Examples from database (don't create them manually)
- Use canonical prompts and scope fixtures for consistency

Available test fixtures:
- `test-fixtures/test-trivial` (TRAIN) - 4 files, 4 TPs
- `test-fixtures/test-validation` (VALID) - 1 file, 1 TP
- `test-fixtures/test-validation-2` (VALID) - 1 file, 1 TP
- `test-fixtures/test-split-test` (TEST) - 1 file, 1 TP
