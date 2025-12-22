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

## Goals

1. **Evolvable agents**: The prompt optimizer can modify not just prompts, but the entire
   agent definition including helper scripts and tooling
2. **Uniform format**: All agent types (critic, grader, optimizer) use the same structure
3. **Single source of truth**: Definitions stored in PostgreSQL, inflated to workspace on demand
4. **Access control**: Database RLS controls which definitions an agent can read/write

## Current State (2025-12-21, updated)

### Completed

**Phase 0-2: Foundation ✅**
- `AgentType` enum with all types: CRITIC, GRADER, PROMPT_OPTIMIZER, CLUSTERING, IMPROVEMENT, FREEFORM
- TypeConfig Pydantic models: `CriticTypeConfig`, `GraderTypeConfig`, `FreeformTypeConfig`, `PromptOptimizerTypeConfig`, `ClusteringTypeConfig`, `ImprovementTypeConfig`
- `AgentConfig` Pydantic model for full agent configuration
- `agent_definitions`, `agent_runs` tables
- `WorkspaceManager`, `AgentHandle`, `AgentRegistry`
- `CaptureTextHandler`, `BootstrapHandler` with `InitFailedError`
- CLI: `agent-definition create/fetch/list/validate`

**Phase 3: Agent Definition Infrastructure ✅**
- `agent_defs/critic/` - Complete definition (AGENT.md, init, examples)
- `agent_defs/grader/` - Complete definition (AGENT.md, init)
- `agent_defs/clustering/` - Complete definition (AGENT.md, init)
- `agent_defs/prompt_optimizer/` - Complete definition (AGENT.md, init)
- `agent_defs/common/` - Shared files (docs/mcp_http_connection.md, examples/mcp_use.py)
- Sync tooling integrates with `adgn-properties db sync`

**Phase 3.5: Wire All Agents to AgentHandle ✅**
- `run_critic()` uses `AgentHandle` infrastructure (definition-based)
- `run_grader()` uses `AgentHandle` (via `_run_grader_agent()`)
- Prompt optimizer uses `run_critic()` with `definition_id` (migrated from legacy)
- System prompts from `AGENT.md` (no Jinja2 for new pattern)
- Bootstrap via `BootstrapHandler` executing `./init`
- Events persisted via `DatabaseEventHandler`

**Phase A: Database Consolidation ✅**
- Task 1: `events.agent_run_id` column (renamed from `transcript_id`)
- Task 2: Clustering migrated to `agent_runs` (migration `20251228000000`)
- Task 2.5: Simplified RLS - only `current_agent_run_id()` remains without SECURITY DEFINER
  - Note: `current_agent_type()` uses SECURITY DEFINER to avoid RLS recursion (migration `20251229000001`)
- Task 3: Legacy tables dropped (`critic_runs`, `grader_runs`, `prompt_optimization_runs`)

**Phase B: Unified Access Control ✅**
- Task 4: All agents use unified `TempUserManager` with `agent_base` role
- Legacy per-type user managers deleted
- RLS policies use `current_agent_run_id()` and inline subqueries

**RLS Design:**
- `current_agent_run_id()` parses username (`agent_{uuid}` pattern), no table access
- `current_agent_type()` uses SECURITY DEFINER to query `agent_runs.type_config` without triggering RLS recursion
- All other RLS policies use inline subqueries against `agent_runs`

### Completed Items

**Schema documentation for all agents ✅ (completed 2025-12-21):**
- Shared schema docs extracted to `common/docs/db/` (critiques.md, grading.md, ground_truth.md, examples.md, evaluation_flow.md, costs.md)
- All agents symlink to relevant schema docs from their `docs/db/` directories
- Clustering retains agent-specific `docs/schema_docs.md` for clustering-specific tables
- Shared reference docs in `common/docs/`: `postgres_access.md`, `rls_mechanism.md`, `mcp_http_connection.md`

**Type-safe config methods on AgentRun ✅ (completed 2025-12-21):**
- Added `.critic_config()`, `.grader_config()`, `.clustering_config()`, `.improvement_config()` methods on `AgentRun` ORM model
- Logic inlined directly into methods (no standalone `require_*_config()` helper functions)
- Methods raise `ValueError` on wrong type
- All call sites use `run.*_config()` pattern
- Cleaner API: `run.critic_config().snapshot_slug` instead of `require_critic_config(run.type_config).snapshot_slug`

**Delete `load_agent_md_from_definition()` ✅ (completed 2025-12-21):**
- This function extracted just AGENT.md text from a definition archive
- Wrong abstraction: agents should unpack definitions first, then read AGENT.md from workspace
- Removed from `agent_handle.py`
- Correct order: unpack → validate (executable `./init`, readable `AGENT.md`) → read → boot agent with bootstrap handler

**Add remaining type-safe config methods ✅ (completed 2025-12-21):**
- Added `.prompt_optimizer_config()` and `.freeform_config()` to `AgentRun`
- All six agent types now have type-safe config accessors

### Legacy Code (To Be Removed in Phase C)

**`run_critic_legacy()` callers:**
- ✅ `gepa_adapter.py` - Intentionally broken (2025-12-21). GEPA raises `NotImplementedError` at runtime entrypoints (`CriticAdapter.__init__`, `optimize_with_gepa`)
- ✅ `tests/props/grader/test_e2e.py` - Migrated to use `run_critic()` with `definition_id` (2025-12-21)

**Completed migrations:**
- `cmd_grade_validation.py` - ✅ Migrated to iterate `AgentDefinition` (with `agent_type=CRITIC`) instead of `Prompt`, uses `run_critic()` with `definition_id` (2025-12-21)
- `run_critic_legacy()` - ✅ DELETED from `critic/critic.py` (2025-12-21)
- `cmd_detector.py` - ✅ DELETED (2025-12-21). Use `adgn-properties run --definition-id <detector>` instead (e.g., `--definition-id dead_code`)

**Supporting legacy artifacts** (to be removed):
- ✅ DELETED (2025-12-21): `critic/prompts/` directory (Jinja2 templates including `critic_system.j2.md`, `dead_code.md`, etc.)
- ✅ DELETED (2025-12-21): `load_and_upsert_detector_prompt()` function from `db/prompts.py`
- ✅ DELETED (2025-12-21): Detector prompt sync logic from `cmd_db.py` (was syncing prompts to `prompts` table)
- ✅ DELETED (2025-12-21): `tests/props/cli/test_critic_prompts_sync.py` (tested deleted functionality)
- ✅ DELETED (2025-12-21): `CriticInput` class from `critic/models.py` (dead code, superseded by `RunCriticInput` and `CriticTypeConfig`)
- ✅ DELETED (2025-12-21): `prompts` table (migration `20260101000000_drop_prompts_table`)
- ✅ RENAMED: `aggregated_recall_by_prompt` view → `aggregated_recall_by_definition`
- ✅ DELETED (2025-12-21): `hash_and_upsert_prompt()` function from `db/prompts.py`
- ✅ DELETED (2025-12-21): `test_prompt_sha` fixture from `tests/props/conftest.py`

### Directory Structure

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

**Full structure conventions:**
- Each agent has `AGENT.md` (system prompt), `init` (bootstrap script), `bin/` (CLI)
- `docs/` can be a symlink (`-> ../common/docs`) or contain agent-specific docs
- `examples/` contains agent-specific example scripts (if needed)
- Critic-based detectors (`dead_code/`, `high_recall_critic/`, etc.) inherit via symlinks to `../critic/`

### Symlink Convention

Agent definitions use symlinks to share common content without duplication:

**Directory symlinks** (preferred for bulk sharing):
```
critic/docs -> ../common/docs
dead_code/init -> ../critic/init
dead_code/bin -> ../critic/bin
```

**File symlinks** (for selective inclusion):
```
clustering/docs/postgres_access.md -> ../../common/docs/postgres_access.md
```

**How it works:**
- When definitions are packed for deployment via `pack_definition()`, external symlinks are resolved
- The symlink target's content is included in the archive (not the symlink itself)
- This allows definitions to reference shared files without hardcoded layering

**Critic-based detectors** inherit from the base critic definition:
- `init`, `bin/`, `docs/`, `examples/` symlink to `../critic/`
- Only `AGENT.md` is detector-specific (the specialized prompt)

See `agent_defs/CLAUDE.md` for link style conventions in markdown files.

### Database Schema

**Tables** (see migrations for full schema):
- `agent_definitions` - Archives with `id`, `agent_type`, `archive` bytea
- `agent_runs` - Unified runs with `agent_run_id`, `type_config` JSONB discriminated by `agent_type`
- `events` - Tool call traces linked via `agent_run_id` (FK to `agent_runs`)
- `reported_issues`, `reported_issue_occurrences` - Critic output (normalized)
- `grading_decisions` - Grader output

**Key migrations:**
- `20251223000000_agent_definitions_squashed.py` - Core tables
- `20251226000001_unified_agent_base_role.py` - Unified `agent_base` role
- `20251226000002_recreate_views_for_agent_runs.py` - Views using `agent_definition_id`
- `20251226000003_drop_legacy_run_tables.py` - Drop legacy per-type tables
- `20251227000000_rename_events_transcript_id.py` - Rename to `agent_run_id`
- `20251228000000_migrate_clustering_to_agent_runs.py` - Clustering migration
- `20251229000001_fix_current_agent_type_recursion.py` - SECURITY DEFINER for `current_agent_type()`
- `20251230000000_migrate_improvement_to_agent_runs.py` - Improvement agent migration
- `20251231000001_recreate_grading_credit_sums_view.py` - Fix missing view for credit validation

### Agent Types

```python
class AgentType(StrEnum):
    CRITIC = "critic"
    GRADER = "grader"
    PROMPT_OPTIMIZER = "prompt_optimizer"
    CLUSTERING = "clustering"
    IMPROVEMENT = "improvement"
    FREEFORM = "freeform"
```

All code must use these enum values, never raw strings.

**FREEFORM type:** Reserved for sub-agents spawned by other agents (e.g., critic delegating
specialized analysis). No repo-backed definition exists - definitions are created programmatically
by parent agents. See "Future: Sub-Agent Spawning" section.

## Access Control

### Current Architecture (Unified Roles) ✅

All agents use a single `agent_base` role with RLS policies based on agent type:

- Username format: `agent_{agent_run_id}`
- Helper functions: `current_agent_run_id()`, `current_agent_type()` (SECURITY DEFINER)
- RLS policies query agent's `type_config` to determine access

**Access patterns by type:**

| Resource | Critic | Grader | Prompt Optimizer |
|----------|--------|--------|------------------|
| Own events | SELECT | SELECT | SELECT (TRAIN only) |
| Own agent_run | SELECT | SELECT | SELECT |
| reported_issues | INSERT own | SELECT graded | SELECT TRAIN only |
| Ground truth | - | SELECT graded snapshot | SELECT TRAIN only |
| grading_decisions | - | INSERT own | SELECT TRAIN only |
| Validation metrics | - | - | Via SECURITY DEFINER only |

**Split-based isolation (prompt optimizer):**
- TRAIN: Full access to ground truth, issues, decisions
- VALID/TEST: Only aggregate metrics via `get_validation_run_aggregates()`

## Runtime Flow

### Initialization Order (Critical)

**CRITICAL: Workspace must be created BEFORE Docker container starts.**

Docker creates bind mount directories as root if they don't exist. This causes
permission errors when unpacking definitions. The correct order is:

```
1. Create AgentRun in database
2. Get workspace path: workspace_manager.get_path(agent_run_id)
3. ensure_definition_unpacked(definition_id, workspace_path)  ← Creates directory AS USER
4. Enter AgentEnvironment context (starts container with mount)
5. Create AgentHandle (loads AGENT.md, builds bootstrap)
6. Run agent loop
```

**Where things happen (code references):**

| Step | Code | File |
|------|------|------|
| 1. Create AgentRun | `session.add(agent_run)` | `critic/critic.py:496-504` |
| 2. Get workspace path | `workspace_manager.get_path()` | `critic/critic.py:510` |
| 3. Unpack definition | `ensure_definition_unpacked()` | `critic/critic.py:511` |
| 4. Enter compositor | `async with comp_ctx` | `critic/critic.py:528` |
| 5. Create AgentHandle | `AgentHandle.create()` | `critic/critic.py:566-575` |
| 6. Run agent | `handle.run()` | `critic/critic.py:580` |

**Common error: "Permission denied" on workspace directory**

If you see `PermissionError: [Errno 13] Permission denied: '.../workspaces/{uuid}'`:
- **Cause**: Docker created the workspaces directory as root in a previous run
- **Fix**: `sudo chown -R $USER:$USER ~/.local/share/adgn/workspaces`
- **Root cause**: A bug or code path where Docker mounts happened before unpacking

### Init Script Responsibilities

Init scripts (`./init`) run at bootstrap before agent sampling:

1. **Print documentation**: MCP connection docs, DB schema, helper functions
2. **Fetch dynamic context**: Snapshot slug, scope from MCP resources
3. **Verify environment**: Database connectivity, required mounts, permissions
4. **Exit non-zero**: To abort agent startup if resources are missing

**Environment variables available:**
- Database: `$PGHOST`, `$PGPORT`, `$PGUSER`, `$PGPASSWORD`, `$PGDATABASE`
- MCP: `$MCP_SERVER_URL`, `$MCP_SERVER_TOKEN`

**What init scripts provide to agents:**
- Critic: `models.py` (ORM), `helpers.py` (issue insertion), snapshot path verification
- Grader: Database access verification, current agent run ID
- Clustering: Database access verification
- Prompt Optimizer: `system_overview.md`, `models.py`, `helpers.py`, example scripts
- Improvement: `system_overview.md`, `models.py`, `helpers.py` (prompt submission)

## Remaining Work (Ordered)

### Phase C: Migrate from `prompt_sha256` to `definition_id`

*Goal: Single identity system based on agent definitions. No dual tracking.*

**Rationale:** Agent definitions (AGENT.md + init + bin/ + helpers) are the complete
specification of agent behavior. Content-addressed `prompt_sha256` only tracks prompt
text, missing init scripts, helpers, and tooling that affect agent performance.

#### Task 5: Migrate Metrics Views ✅

**Status:** Complete (2025-12-20)

**Completed:**
1. View renamed `aggregated_recall_by_prompt` → `aggregated_recall_by_definition` (migration `20251226000002`)
2. GROUP BY changed from `prompt_sha256` to `agent_definition_id`
3. ORM model renamed: `AggregatedRecallByPrompt` → `AggregatedRecallByDefinition`
4. All related views updated to use `agent_definition_id`
5. Tests migrated to use `synced_test_db` fixture (which syncs agent definitions)
6. Added migration `20251231000001_recreate_grading_credit_sums_view.py` to fix missing view

**Bug fix:** Migration `20251226000000` dropped `grading_credit_sums` view but never recreated it.
This broke the `check_credit_sum` trigger. Fixed by creating migration `20251231000001` which:
- Recreates `grading_credit_sums` view using `agent_run_id` (not legacy `grader_run_id`)
- Recreates `check_credit_sum` function using `agent_run_id`
- Restores the `enforce_credit_sum` trigger on `grading_decisions`

**View change:**
```sql
-- Key columns changed from:
(split, prompt_sha256, critic_model, scope_kind)
-- To:
(split, agent_definition_id, critic_model, scope_kind)
```

**Files updated:**
- `db/models.py` - ORM model renamed
- `cli/cmd_stats.py` - Queries updated
- `agent_defs/prompt_optimizer/examples/*.py` - Queries updated
- `prompt_optimize/prompt_optimizer.py` - View references updated
- Documentation: `AGENTS.md`, `system_overview.md`, `agent_infrastructure.md`
- Tests: Changed from `test_db` to `synced_test_db` fixture

#### Task 6: Migrate `cmd_grade_validation` ✅

**Status:** Complete (2025-12-21)

**Changes made:**
- Iterates over `AgentDefinition` (where `agent_type = 'critic'`) instead of `Prompt` table
- Uses `run_critic()` with `definition_id` instead of `run_critic_legacy()` with `prompt_sha256`
- Updated imports and removed `CriticInput` usage

#### Task 7: Unified Optimization Toolkit

**Status:** Complete ✅ (2025-12-21)

**Key insight:** Prompt optimizer and improvement agent use the **same toolkit**, differing only
in RLS-scoped access. Both work at the **agent definition level** (full archives with AGENT.md,
bin/, examples/, etc.), not just prompt text.

**Completed:**
- `load_agent_md_from_definition()` removed ✅ (was wrong abstraction)
- Unified `PromptEvalServer` MCP server implemented ✅
- Improvement agent E2E tests passing ✅ (with mocked termination condition)
- Both agents use the same tools via MCP-over-HTTP

##### 7a: Unified MCP Server for Optimization Agents ✅

Both prompt optimizer and improvement agent share `PromptEvalServer` with these tools:

**MCP Tools (orchestration only):**

1. **`create_critic_definition`** - Pack directory into new agent definition
   ```python
   Input: definition_dir: str, rationale: str, expected_improvement: str
   Output: definition_id: str, message: str
   ```

2. **`run_critic`** - Run critic with definition on an example
   ```python
   Input: definition_id: str, snapshot_slug: str, scope_hash: str
   Output: critic_run_id: UUID
   ```

3. **`run_grader`** - Grade a critic run
   ```python
   Input: critic_run_id: UUID
   Output: grader_run_id: UUID
   ```

**Implementation:** `src/adgn/props/prompt_optimize/prompt_optimizer.py` (`PromptEvalServer` class)

**Reads are via SQL + CLI helpers (not MCP):**
- Agent has `psql` access with RLS-scoped credentials
- CLI: `adgn-properties definition fetch <id>` to get archive contents
- CLI: `adgn-properties definition list` to list available definitions
- SQL: Query `agent_runs`, `grading_decisions`, `events` for results/traces
- All reads go through RLS policies based on agent type

##### 7b: Improvement Agent Input Interface ✅

**Status:** Complete (2025-12-21)

The improvement agent receives 1+ definition IDs and 1+ example IDs:

```python
class AllowedExample(BaseModel, frozen=True):
    """Reference to an example by snapshot and scope. Frozen for hashability."""
    snapshot_slug: SnapshotSlug
    scope_hash: str

class ImprovementTypeConfig(BaseModel):
    agent_type: Literal[AgentType.IMPROVEMENT] = AgentType.IMPROVEMENT
    baseline_definition_ids: list[str] = Field(
        min_length=1, description="One or more agent definition IDs to study and improve"
    )
    allowed_examples: list[AllowedExample] = Field(
        min_length=1, description="One or more (snapshot_slug, scope_hash) pairs to evaluate on"
    )
```

**Validation:** Both fields require at least one element (`min_length=1`). Empty lists raise `ValidationError`.

**Use cases:**
- Single definition, multiple examples: Improve one critic across diverse code
- Multiple definitions, single example: Compare approaches on one codebase
- Multiple definitions, multiple examples: Comprehensive improvement study

##### 7c: RLS Differentiates Access (Updated 2025-12-21)

**Key design decisions:**

1. **Ground truth access:** Improvement agent has the **same access as prompt optimizer** (full TRAIN split).
   Both agents need to understand ground truth patterns to improve prompts.

2. **Definition access:** Minimal-access model for agent_definitions table:

| Agent | Ground Truth | Definition Access | Example Access |
|-------|--------------|-------------------|----------------|
| Default (all agents) | Per-type rules | Own definition + created definitions | Per-type rules |
| Prompt Optimizer | TRAIN only | **All definitions** | All TRAIN examples |
| Improvement Agent | TRAIN only | Own + created + **baseline_definition_ids** | All TRAIN examples |

**Rationale for definitions access:**
- Default: Agents should only see definitions relevant to their task
- Optimizer sees all: needs to analyze and compare different prompts across the system
- Improvement sees baselines: needs to study the definitions it's improving, but not unrelated ones

**RLS implementation:**
- Both use `TempUserManager` with unified `agent_base` role
- `current_agent_type()` returns `prompt_optimizer` or `improvement`
- Both agent types use `is_train_snapshot()` for ground truth access (same policy)
- `agent_definitions` policy uses:
  - `get_current_agent_definition_id()` for own definition
  - `created_by_agent_run_id = current_agent_run_id()` for created definitions
  - `get_improvement_baseline_definition_ids()` for improvement agent baselines
- `allowed_examples` in type_config defines the **termination condition**, not data access

##### 7d: Remove `load_agent_md_from_definition()` ✅

**Status:** Complete (2025-12-21)

This function encouraged the wrong abstraction (extracting AGENT.md directly from archive). Deleted it:
- Agents now unpack definitions first, then read AGENT.md from workspace
- Correct order: unpack → validate → read → boot agent with bootstrap handler
- `ensure_definition_unpacked()` validates both executable `./init` and readable `AGENT.md`

##### 7e: Completion Criteria ✅

**Status:** Complete (2025-12-21)

**Termination condition:** `ImprovementReminderHandler` checks after each agent turn whether
a created definition beats the baseline average on total issues found across allowed_examples.

**Implementation:** `src/adgn/props/prompt_improve/reminder_handler.py`
- `check_termination_condition()` queries grader results for all candidate definitions
- Compares `best_candidate_issues` against `baseline_avg_issues`
- Returns `TerminationStatus` with `should_terminate=True` when threshold met

**Workflow:**
1. Agent receives baseline definition IDs and training examples (via type_config)
2. Agent fetches baseline definitions via SQL/CLI
3. Agent queries existing runs, grader results, failure patterns via SQL
4. Agent creates improved definition at `/workspace/improved/`
5. Agent calls `create_critic_definition` → gets new `definition_id`
6. Agent calls `run_critic` + `run_grader` on training examples
7. `ImprovementReminderHandler` checks termination after each turn
8. Agent loop terminates when created definition beats baseline average

**E2E tests:** `tests/props/prompt_improve/test_e2e.py` validates the full workflow
with mocked termination condition (to avoid needing real evaluations in tests).

#### Task 8: Migrate `cmd_detector` ✅

**Status:** Complete (2025-12-21)

**Resolution:** `cmd_detector.py` was DELETED entirely. Users should now use:
```bash
adgn-properties run --definition-id <detector>
# e.g., adgn-properties run --definition-id dead_code --snapshot <slug>
```

This is cleaner than migrating the old command - the unified `run` command already supports definition-based execution.

#### Task 9: Break GEPA (Intentional) ✅

**Status:** Complete (2025-12-21)

**Decision:** GEPA is intentionally broken until adapted to definition-based evolution.

**Changes made:**
1. `run_critic_legacy()` deleted from `critic/critic.py`
2. `gepa_adapter.py` now raises `NotImplementedError` at runtime entrypoints:
   - `CriticAdapter.__init__()` calls `_gepa_not_implemented()`
   - `optimize_with_gepa()` calls `_gepa_not_implemented()`
3. Error message directs to this doc for migration plan
4. GEPA adapter code preserved but unreachable (for future migration reference)

**Remaining work (for GEPA migration later):**
- GEPA adapter needs redesign to evolve full definitions (not just prompt text)
- Leave GEPA broken for now - it's a research tool, not production path

#### Task 10: Remove Legacy Artifacts ✅

**Status:** Complete (2025-12-21)
**Dependencies:** Tasks 5-9 complete ✅

**Completed:**
1. ✅ `run_critic_legacy()` function deleted (2025-12-21)
2. ✅ Jinja2 templates removed (`critic/prompts/` directory deleted, 2025-12-21)
3. ✅ Legacy imports cleaned from `critic/critic.py`, grader tests

**Remaining:**
*(All items completed)*

**Completed:**
1. ✅ Dropped `prompts` table (migration `20260101000000_drop_prompts_table`) (2025-12-21)
2. ✅ Removed `hash_and_upsert_prompt()` from `db/prompts.py` (2025-12-21)
3. ✅ Removed `CriticInput` class (dead code, superseded by `RunCriticInput` and `CriticTypeConfig`) (2025-12-21)
4. ✅ Cleaned up unused `test_prompt_sha` fixture parameters from tests (2025-12-21)

**Phase D: Agent-Specific CLIs ✅**

*Goal: Replace Python examples and scattered helpers with discoverable CLI commands.*

#### Task 7: Implement Agent CLIs ✅

**Status:** Complete (2025-12-20)

**Completed:**
1. Created `agent_defs/critic/bin/critique.py` - Critic CLI with insert-issue, insert-occurrence, submit, list-issues, delete-issue
2. Created `agent_defs/grader/bin/grader.py` - Grader CLI with add-tp-match, add-fp-match, add-no-match, delete-decision, submit
3. Created `agent_defs/clustering/bin/clustering.py` - Clustering CLI with create-cluster, assign-to-cluster, assign-to-tp, assign-to-fp, cancel-assignment
4. Created `agent_defs/prompt_optimizer/bin/optimizer.py` - Optimizer CLI with upsert-prompt, run-critic, run-grader, report-failure
5. Created `agent_defs/improvement/bin/improvement.py` - Improvement CLI with submit-prompt
6. All scripts use `python /workspace/bin/<script>.py` pattern (full paths, no PATH manipulation)
7. All init scripts import CLI module and print `__doc__` for discovery
8. Removed `adgn-properties agent-helper` CLI (agents use bin/ scripts directly)
9. Deleted old `cli_helpers.py` files from critic/, grader/, prompt_optimize/, prompt_improve/

**Pattern established:**
- CLI scripts are `.py` files in `bin/` directory (importable as modules)
- Each `bin/` has `__init__.py` to make it a package
- Init scripts: `from bin import <module>; print(<module>.__doc__)`
- Usage: `python /workspace/bin/<script>.py <command> [args]`
- All scripts are executable (`chmod +x`) with `#!/usr/bin/env python3`

## Future: Sub-Agent Spawning (FREEFORM type)

Agents can spawn sub-agents for task decomposition. A critic might delegate
"trace the architecture" or "look for type errors" to specialized sub-agents.

**FREEFORM agent type:**
- No repo-backed definition (created programmatically by parent)
- Used by: critic (code analysis delegation), prompt optimizer (evaluation orchestration)
- Later: improvement agent may also spawn sub-agents

**Workflow:**
1. Parent creates ad-hoc definition directory with AGENT.md + init
2. Registers via `agent-helpers agent-definition create --type freeform`
3. Spawns via `create_subagent(definition_id)`
4. Converses via `run_subagent(agent_run_id, message)`

**Key properties:**
- Sub-agent gets own `agent_run_id` with `parent_agent_run_id` pointing to parent
- Inherits snapshot mount from parent (for critics)
- Workspace persists at `~/.local/share/adgn/workspaces/{agent_run_id}/`
- Container can be restarted; transcript reconstructed from events table

## Future: Recursive Cost Aggregation

Agents spawn sub-agents which can spawn further sub-agents. For billing and
resource tracking, we need to aggregate costs across the entire sub-tree.

**Planned columns on `agent_runs` or `run_costs` view:**
- `own_cost` - Cost of this agent run only (tokens, API calls)
- `cost_including_subagents` - Recursive sum of own_cost + all descendant costs

**Implementation approach:**
- Recursive CTE or materialized view joining on `parent_agent_run_id`
- Query: `WITH RECURSIVE subtree AS (...) SELECT SUM(own_cost)`
- Consider caching for deep trees (3+ levels)

## Agent-Specific CLIs via `bin/` (Implemented)

Each agent definition includes a `bin/` directory with executable CLI scripts.
This replaces scattered Python examples and the removed `adgn-properties agent-helper`
CLI with discoverable, agent-specific commands.

### Current Structure

See "Directory Structure" section above for the full layout.

### Agent CLI Commands (Implemented)

| Agent | Script | Subcommands |
|-------|--------|-------------|
| Critic | `critique.py` | `insert-issue`, `insert-occurrence`, `submit`, `list-issues`, `delete-issue` |
| Grader | `grader.py` | `add-tp-match`, `add-fp-match`, `add-no-match`, `delete-decision`, `submit` |
| Clustering | `clustering.py` | `create-cluster`, `assign-to-cluster`, `assign-to-tp`, `assign-to-fp`, `cancel-assignment` |
| Prompt Optimizer | `optimizer.py` | `create-critic-definition`, `run-critic`, `run-grader` |
| Improvement | `improvement.py` | Uses unified `PromptEvalServer` via MCP |

### Usage Pattern

Agent uses shell commands with `python` prefix and full paths:

```bash
# Example commands
python /workspace/bin/critique.py insert-issue dead-import "Unused import at line 15"
python /workspace/bin/critique.py submit 1 "Found 1 dead import issue"
python /workspace/bin/grader.py add-tp-match "input-001" "tp-042" "occ-001" 1.0 "Exact match"
python /workspace/bin/optimizer.py run-critic "snapshot-slug" "scope-hash" "prompt-sha256"

# Discover commands
python /workspace/bin/critique.py --help
```

### Init Script Pattern

Init scripts import the CLI module and print its docstring for discovery:

```python
# Print CLI usage from bin/critique module docstring
print_section("Critic CLI Commands")
from bin import critique as critique_cli
print(critique_cli.__doc__)
```

### Benefits

1. **Discoverable**: `--help` shows available commands
2. **Testable**: Commands work outside agent with environment variables
3. **Shell-friendly**: Works with heredocs, pipes, standard patterns
4. **Self-contained**: Each definition includes its own tooling
5. **Importable**: `.py` extension allows init scripts to print docstrings

### Future: Shared Utilities (common/bin/)

Optional shared commands available to all agents (not yet implemented):

- `db-query` - Execute SQL query and print results
- `db-schema` - Print table schema
- `run-info` - Show current agent run ID, type, status

These would be merged into each agent's workspace via the existing `common/` merge logic.

### Environment Variables

All agent containers receive these environment variables (set by `AgentEnvironment` in `agent_setup.py`):

- `AGENT_RUN_ID` - UUID of the current agent run (unified for all agent types)
- `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` - Database connection (temp user credentials)
- `MCP_SERVER_URL`, `MCP_SERVER_TOKEN` - MCP HTTP server connection

The unified `AGENT_RUN_ID` works because all agents use the same `agent_runs` table with
`type_config` JSONB discriminating the agent type. RLS policies use `current_agent_run_id()`
which parses the username pattern `agent_{uuid}`.

Each init script prints the `AGENT_RUN_ID` in its environment info section for visibility.

## Completed: Prompt Optimizer Examples Migration ✅

Prompt optimizer examples have been migrated to agent definitions:

**New location:** `agent_defs/prompt_optimizer/examples/`
- `listing.py` - List examples/snapshots by split/scope
- `definition_stats_targeted.py` - Definition stats via views (targeted mode)
- `definition_stats_whole_repo.py` - Definition stats via SECURITY DEFINER (whole-repo mode)
- `pareto.py` - Pareto frontier analysis
- `evaluation_pipeline.py` - Async run_critic/run_grader usage

**Test imports updated:** `tests/props/prompt_optimize/examples/` now imports from `adgn.props.agent_defs.prompt_optimizer.examples.*`

## Future: Dissolve agent_queries.py

The `db/agent_queries.py` module contains SQL template queries for agent analysis.
These should be refactored into the agent definition layer:

**Current location:** `src/adgn/props/db/agent_queries.py`

**Target location:** Agent-specific CLI commands or example scripts:
- `agent_defs/critic/bin/critique` - `query-traces` subcommand
- `agent_defs/grader/bin/grade` - `query-decisions` subcommand
- `agent_defs/common/bin/db-query` - Generic query utility

**Rationale:**
- SQL queries are agent-specific documentation, not core DB infrastructure
- CLI commands are more discoverable than example scripts
- Follows the pattern of keeping agent-specific content under agent directories
- Typed CLI with Typer is more robust than SQL templates with placeholders

## References

- Agent definitions: `src/adgn/props/agent_defs/`
- AgentHandle: `src/adgn/props/agent_handle.py`
- AgentRegistry: `src/adgn/props/agent_registry.py`
- TempUserManager: `src/adgn/props/db/temp_user_manager.py`
- Migrations: `src/adgn/props/db/migrations/versions/`
- E2E tests: `tests/props/critic/test_e2e.py`, `tests/props/grader/test_e2e.py`
