# Evaluation Results Database

## Overview

PostgreSQL database for evaluation results with:
- Structured query interface (psql CLI, SQLAlchemy)
- Row-level security for train/valid/test access control
- Event tracking for full agent trajectories
- Deduplication (prompts by SHA256)

## Architecture

```
┌─────────────────────────────────────────┐
│ Eval Tools (host)                       │
│ - CriticRun, GraderRun managers         │
│ - DatabaseEventHandler                  │
└──────────────┬──────────────────────────┘
               │ writes as admin_user
               ↓
┌─────────────────────────────────────────┐
│ PostgreSQL (eval_results database)      │
│                                         │
│ Tables:                                 │
│ ├── specimens (slug → split)            │
│ ├── prompts (dedup by SHA256)           │
│ ├── prompt_optimization_runs            │
│ ├── critiques (UUID PK)                 │
│ ├── critic_runs → critique              │
│ ├── grader_runs → critique              │
│ └── events (transcript_id → runs)       │
│                                         │
│ Views:                                  │
│ └── valid_grader_metrics (aggregates)   │
│                                         │
│ Users: admin_user, agent_user           │
│ RLS: agent sees train details only      │
│      + valid aggregates via view        │
└─────────────────────────────────────────┘
```

## Schema Summary

**Core tables** (see `src/adgn/props/db/models.py` for SQLAlchemy definitions):

- **`specimens`**: specimen slug → split (train/valid/test) mapping
- **`prompts`**: SHA256(64) → prompt_text, deduplicated
- **`prompt_optimization_runs`**: UUID PK, links optimization sessions to runs
- **`critiques`**: UUID PK, JSONB payload (CriticSubmitPayload), FK to specimen
- **`critic_runs`**: int PK, transcript_id (UUID), FK to prompt_sha256, specimen, critique_id (nullable), optimization_run_id (nullable), files (JSONB), output (JSONB)
- **`grader_runs`**: int PK, transcript_id (UUID), FK to specimen, critique_id, optimization_run_id (nullable), output (JSONB)
- **`events`**: int PK, transcript_id (UUID), sequence_num, event_type, payload (JSONB), UNIQUE(transcript_id, sequence_num)

**Views:**
- **`valid_grader_metrics`**: Pre-filtered view of grader_runs for valid split only, extracting recall/precision/tp/fp/fn from JSONB for convenient aggregate queries by agent_user

**Key changes from file-based storage:**
- ✅ No `input` JSONB columns (fields extracted to proper columns)
- ✅ `transcript_id` (not `agent_run_id`) - shared UUID for critic+grader+events
- ✅ `prompt_sha256` (not `prompt_hash`) - validated String(64)
- ✅ `Critique.id` is UUID (enables hash-based deduplication later)
- ✅ `GraderInput` references `critique_id` (not embedded `critic_result`)
- ✅ `CriticRun` has `files` column for scope tracking

**Relationships:**
- `Specimen` (1) ← (many) `CriticRun`, `Critique`, `GraderRun`
- `Critique` (1) ← (0..1) `CriticRun.critique_id` (produced by, nullable if failed)
- `Critique` (1) ← (many) `GraderRun.critique_id` (graded by)
- `Prompt` (1) ← (many) `CriticRun` (grader not directly linked to prompt)
- `PromptOptimizationRun` (1) ← (many) `CriticRun`, `GraderRun` (nullable FK)
- `transcript_id` (UUID) → (many) `Event` (one execution = many events)

**Link from grader to prompt** (indirect): `GraderRun → Critique → CriticRun → Prompt`

## Database Users and RLS

**admin_user** (eval tools):
- Full read/write access to all tables
- Used by `CriticRun._write_to_db()`, `GraderRun._write_to_db()`
- Connection via admin credentials from environment

**agent_user** (optimization agents):
- SELECT on all tables, BUT:
  - **Train split**: Full detail access to `specimens`, `critiques`, `critic_runs`, `grader_runs`, `events`
  - **Valid split**: Aggregate metrics ONLY via `valid_grader_metrics` view
    - RLS blocks direct queries to `critiques`, `critic_runs`, `grader_runs`, `events` for valid specimens
  - **Test split**: Completely hidden (all data blocked)
- Connection via agent credentials from environment
- RLS policies managed by SQLAlchemy metadata (`enable_rls()`)

**RLS policy summary** (enforced by PostgreSQL):
```sql
-- Agent can only see train split details
WHERE specimen IN (SELECT specimen FROM specimens WHERE split = 'train')

-- Valid split aggregates accessible ONLY via valid_grader_metrics view
SELECT * FROM valid_grader_metrics  -- Pre-filtered to valid split
```

## Event Tracking

`DatabaseEventHandler` (replaces file-based `TranscriptHandler`):
- Writes events to `events` table during agent execution
- Each event: transcript_id, sequence_num, event_type, timestamp, payload (JSONB)
- Query full trajectory: `SELECT * FROM events WHERE transcript_id='...' ORDER BY sequence_num`
- Shared transcript_id across critic + grader enables unified event stream

## Setup and Management

**Docker Compose** (`src/adgn/props/docker-compose.yml`):
- PostgreSQL 16 container with named volume `eval_results_data`
- Health checks, automatic user/db creation via `init_db.sh`

**Setup script** (`src/adgn/props/db/init_db.sh`):
- Creates database `eval_results`, `eval_results_test`
- Creates users: `admin_user`, `agent_user` with generated passwords
- Grants permissions

**Schema management** (Alembic):
- Migrations in `src/adgn/props/db/alembic/versions/`
- Initial schema: `2eef3c984bc3_initial_schema.py` (includes tables, RLS policies, and valid_grader_metrics view)
- Run: `alembic upgrade head` (from `src/adgn/props/db/`)

**SQL Query Constants** (`src/adgn/props/db/agent_queries.py`):
- Shared SQL constants for prompt optimizer system prompts
- All queries tested against populated database with RLS verification
- Constants interpolated into Jinja2 templates via `render_prompt_template()`
- Includes both working queries (train access, valid aggregates) and blocked queries (valid details)

**Python session management** (`src/adgn/props/db/session.py`):
- `init_db(db_url)` - initialize engine and session
- `drop_tables()` - drop all tables (for testing)
- `get_session()` - context manager for database sessions
- Note: RLS policies and views are managed by SQLAlchemy metadata (`enable_rls()`), not Alembic

**Verification**:
- Run integration tests: `pytest tests/props/db/test_db_integration.py -v`
- Tests verify: connection, schema creation, RLS policies, write/read access

## Implementation Status

### ✅ Completed

**Phase 1: Prompt Optimizer Enhancements**
- ✅ Updated prompt optimizer system prompts with:
  - ✅ DB schema reference (tables, key columns, RLS policies)
  - ✅ SQL query examples via shared constants in `agent_queries.py`
  - ✅ Train vs valid/test access rules (detailed RLS explanation)
  - ✅ Examples of blocked queries (what won't work for valid split)
  - ❌ Cost tracking/accounting instructions (not implemented)
- ✅ All SQL queries DRY - defined once in `agent_queries.py`, used in both tests and templates
- ✅ Integration tests verify RLS policies work correctly for agent_user

**Phase 2: Validation Aggregates**
- ✅ Implemented: `valid_grader_metrics` view for agent aggregate queries
- ✅ RLS policy restricts agent_user to view-only access for valid split
  - Direct queries to `grader_runs` for valid split return 0 rows (blocked by RLS)
  - Agent must use `valid_grader_metrics` view for valid split metrics
  - This prevents leaking detailed critique rationales or execution traces
- ✅ View automatically updated (no REFRESH needed - regular view, not materialized)
- ✅ Tests verify: agent can query view, cannot query grader_runs directly for valid

**Code Cleanup**
- ✅ Inlined single-use functions from `runs_context.py`:
  - ✅ `cluster_output_dir()` → inlined into `cluster_unknowns.py`
  - ✅ `prompt_evals_dir()` → inlined into `prompt_optimizer.py`
  - ✅ `adhoc_run_dir()` → inlined into `prompt_optimizer.py`

### 🔨 Remaining Tasks

**Phase 3: Cleanup and Optimization**
- [ ] Hash-based critique deduplication:
  - [ ] Add `critique_hash` column (SHA256 of payload)
  - [ ] Upsert logic: check hash before inserting new critique
  - [ ] Update `CriticRun._write_to_db()` to use upsert
- [ ] Migrate specimen splits to manifests (per TODO in `splits.py`):
  - [ ] Add `split: train|valid|test` field to `manifest.yaml`
  - [ ] Update `sync_specimens.py` to read from manifests
  - [ ] Remove `SPECIMEN_SPLITS` dict from `splits.py`
  - Note: Syncing from `splits.py` → DB is already implemented (auto-runs on first DB operation)
- [ ] Performance:
  - [ ] Add indexes for common queries (check `EXPLAIN` output)
  - [ ] Consider partitioning `events` by timestamp if volume grows
- [ ] Monitoring:
  - [ ] Database size tracking
  - [ ] Query performance metrics
  - [ ] RLS policy verification in CI

**Phase 4: Eval Harness Integration (lower priority)**
- [ ] Design schema for `eval_harness.py` results:
  - Currently writes JSON files (case payloads, summary.json, index.json)
  - Needs: evaluation spec, case results, expectations, diffs
  - Separate concern from critic/grader runs

### Migration Status

**Migrated to DB:**
- `run_managers.py` - CriticRun, GraderRun persistence
- `agent/db_event_handler.py` - event tracking
- All formal evaluation paths (CLI, MCP servers, grade_runner)

**Keeping Files:**
- CLI/UI output (user-facing convenience)
- Specimen source code and archives
- Optimization agent workspace (prompt_optimizer)
- Cluster analysis output (cluster_unknowns)
- Ad-hoc run outputs (not formal evaluations)

**Not Migrated:**
- `eval_harness.py` - needs separate schema design

## Benefits vs File-Based Storage

- **Access control**: RLS enforces train vs valid/test visibility automatically
- **Deduplication**: Prompts stored once by SHA256
- **Structured queries**: SQL for filtering, aggregation, comparison
- **Event tracking**: Full trajectory in one table, queryable by transcript_id
- **Relationships**: Proper FKs ensure data integrity
- **Concurrent access**: Multiple tools can write/read simultaneously
- **No file parsing**: Direct JSONB queries for metrics
- **Split isolation**: Test data completely hidden from optimization agents
