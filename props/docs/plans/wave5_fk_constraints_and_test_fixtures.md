# Wave 5: FK Constraints and Test Fixture Fixes

**Status:** In progress
**Branch:** `claude/critic-agent-tools-2rGAx`
**Last Updated:** 2025-12-23

## Problem Statement

### Occurrence-Weighted Recall Constraint (must keep normalization late)

Recall metrics must stay occurrence-weighted. Do **not** average per-grader recall ratios early. Keep raw totals through aggregation (e.g., “total credit per grader run”, “total catchable occurrences per example/critic run”) and only divide by the catchable-occurrence count at the final step. This avoids inflating recall when multiple graders grade the same critic run.

Implementation rule for views:
- Keep lower views (`occurrence_credits`, `occurrence_run_credits`, `critic_run_occurrence_stats`) in **totals space** (store `total_credit`, carry `n_catchable_occurrences`).
- At the top-level recall views (`critic_run_occurrence_stats` projections, `aggregated_recall_by_example`, `aggregated_recall_by_definition`), derive recall columns in SQL as `total_credit`-based stats divided by `n_catchable_occurrences`:
  - `recall_mean = (occurrences_caught_stats).mean / NULLIF(n_catchable_occurrences, 0)`
  - `recall_ci_low = (occurrences_caught_stats).ci_low / NULLIF(n_catchable_occurrences, 0)`
  - `recall_ci_high = (occurrences_caught_stats).ci_high / NULLIF(n_catchable_occurrences, 0)`
- Use these derived recall fields for ordering/filtering; never average per-grader 0..1 ratios directly.
- When a credit ratio is needed (e.g., for ordering), compute it in SQL from the totals (`total_credit` / `n_catchable_occurrences`) at the view edge—do not push 0..1 ratios down into intermediate views or Python.
- Failed critic runs must count as 0 credit (not dropped). When no grader credits exist, default the credit array to `[0.0]` so recall is 0/n_catchable rather than NULL.
- Strong preference: tests and fixtures should reuse synced, in-git specimens instead of fabricating TP/FP IDs. Add shared fixtures (in `tests/props/conftest.py`) that return real `(tp_id, occurrence_id)` from git-synced snapshots and use them for grading_decisions / OccurrenceResult construction.

### Fixture Set Extension (synced specimens, no fabrication)
- Snapshot: continue using `test-fixtures/test-trivial` (git-synced).
- Ensure it contains:
  - File-set example A with exactly 1 TP occurrence (already present: subtract.py).
  - File-set example B with ≥2 TP occurrences (e.g., add.py/multiply.py) to exercise multi-occurrence aggregation.
  - At least 1 FP occurrence (added `test-fp.yaml` to test-trivial) to cover FP-side views/constraints.
  - Whole-snapshot example (implicit for the snapshot) for whole-scope paths.
- Shared fixtures to add/use:
  - `fixture_example_subtract` → single-file-set example with 1 catchable TP.
  - `fixture_example_multi_tp` → file-set example with multiple TP occurrences.
  - `fixture_tp_occurrence` / `fixture_multi_tp_occurrences` → real (tp_id, occurrence_id) tuples from the snapshot.
  - `fixture_fp_occurrence` → real FP occurrence (must exist; fixtures should fail fast if it goes missing).
  - Helpers to build critic runs + grader runs + grading_decisions using these real IDs (avoid synthetic "tp-001"/"occ-1").
- Tests that currently fabricate TP/FP IDs should be refactored to consume these fixtures; avoid “clunky refetching”—fetch once via shared fixtures and pass IDs through helpers.

### Root Cause: Missing Referential Integrity

The `grading_decisions` table allowed inserting rows with `target_tp_id` and `target_tp_occurrence_id` values that did not exist in the `true_positives` / `true_positive_occurrences` tables. This violated the fundamental invariant that grader-produced TP/FP IDs must reference actual ground truth records.

**Symptom discovered:** Test fixtures were creating fake TP IDs like `"tp-001"`, `"tp-002"` that didn't exist in the database, causing recall calculations to reach impossible values (e.g., 380% recall) when occurrence credits were summed against non-existent occurrences.

### Why Standard FKs Cannot Be Used

Standard PostgreSQL foreign keys require the referencing table to have the FK column(s) directly. However:

- `grading_decisions.target_tp_id` references `true_positives(snapshot_slug, tp_id)`
- `grading_decisions` does NOT have a `snapshot_slug` column
- The `snapshot_slug` must be derived via:
  1. `grading_decisions.agent_run_id` → `agent_runs.type_config`
  2. `type_config.graded_agent_run_id` → graded critic's `agent_runs.type_config`
  3. Critic's `type_config.example.snapshot_slug`

This multi-hop derivation through JSONB prevents standard FK constraints.

## Solution: Trigger-Based Validation

Added two trigger functions to the squashed migration (`20251223000000_schema_squashed.py`):

### 1. `check_grading_target_exists()` (lines 648-704)

Validates that `grading_decisions` rows reference valid TP/FP occurrences:

```sql
CREATE FUNCTION check_grading_target_exists() RETURNS trigger
-- Derives snapshot_slug from grader → critic → example
-- Validates target_tp_id/target_tp_occurrence_id exists in true_positive_occurrences
-- Validates target_fp_id/target_fp_occurrence_id exists in false_positive_occurrences
```

### 2. `check_unknown_mapping_exists()` (lines 706-762)

Validates that `unknown_assignments` rows reference valid TP/FP records:

```sql
CREATE FUNCTION check_unknown_mapping_exists() RETURNS trigger
-- Validates mapped_tp_id exists in true_positives
-- Validates mapped_fp_id exists in false_positives
```

### 3. Triggers (lines 1571-1587)

```sql
CREATE TRIGGER check_input_issue_exists_trigger
  BEFORE INSERT OR UPDATE ON grading_decisions
  FOR EACH ROW EXECUTE FUNCTION check_input_issue_exists();

CREATE TRIGGER check_grading_target_exists_trigger
  BEFORE INSERT OR UPDATE ON grading_decisions
  FOR EACH ROW EXECUTE FUNCTION check_grading_target_exists();

CREATE TRIGGER check_unknown_mapping_exists_trigger
  BEFORE INSERT OR UPDATE ON unknown_assignments
  FOR EACH ROW EXECUTE FUNCTION check_unknown_mapping_exists();
```

## Test Fixture Changes

### `make_grader_output()` Signature Change

**Before:**
```python
def make_grader_output(*, tp_count: int, ...) -> DBGraderOutput:
    # Created synthetic IDs: "tp-001", "tp-002", ...
```

**After:**
```python
def make_grader_output(
    *,
    tp_occurrences: list[tuple[str, str]],  # [(tp_id, occurrence_id), ...]
    summary: str = "Test grader output",
    found_credit: float = 0.0,
    unknowns: list[str] | None = None,
) -> DBGraderOutput:
    # Uses real TP IDs from database
```

### New Helper Function

```python
def get_tp_occurrences_for_snapshot(
    snapshot_slug: str, session: Session
) -> list[tuple[str, str]]:
    """Query real TP occurrences for a snapshot."""
    rows = (
        session.query(TruePositiveOccurrenceORM.tp_id, TruePositiveOccurrenceORM.occurrence_id)
        .filter_by(snapshot_slug=snapshot_slug)
        .order_by(TruePositiveOccurrenceORM.tp_id, TruePositiveOccurrenceORM.occurrence_id)
        .all()
    )
    return [(row.tp_id, row.occurrence_id) for row in rows]
```

### Files Updated

- `tests/props/conftest.py` - Factory functions and helper
- `tests/props/grader/conftest.py` - Test fixtures
- `tests/props/prompt_optimize/examples/test_pareto.py` - Test callers
- `tests/props/prompt_optimize/examples/test_definition_stats_targeted.py` - Test callers
- `tests/props/gepa/test_warm_start.py` - Test callers (skipped tests)

## Key Enums (Must Be StrEnum, Not str)

All these enums are defined using `enum.StrEnum` and must be used as enum values, not raw strings:

| Enum | Location | Values |
|------|----------|--------|
| `Split` | `splits.py:23` | `TRAIN`, `VALID`, `TEST` |
| `AgentType` | `agent_types.py:20` | `CRITIC`, `GRADER`, `PROMPT_OPTIMIZER`, `CLUSTERING`, `IMPROVEMENT`, `FREEFORM` |
| `AgentRunStatus` | `db/models.py:133` | `IN_PROGRESS`, `COMPLETED`, `MAX_TURNS_EXCEEDED`, `CONTEXT_LENGTH_EXCEEDED`, `REPORTED_FAILURE` |
| `ExampleKind` | `models/examples.py:18` | `WHOLE_SNAPSHOT`, `FILE_SET` |
| `TargetMetric` | `prompt_optimize/target_metric.py:6` | Values depend on implementation |
| `BudgetState` | `prompt_optimize/budget_handler.py:31` | Values depend on implementation |
| `FileType` | `paths.py:12` | Values depend on implementation |

## Stable State Indicators

### Database Schema
- [ ] All migrations apply cleanly: `alembic upgrade head`
- [ ] Database recreate succeeds: `props db recreate --yes`
- [ ] Triggers exist: `check_input_issue_exists_trigger`, `check_grading_target_exists_trigger`, `check_unknown_mapping_exists_trigger`
- [ ] Trigger functions exist: `check_input_issue_exists()`, `check_grading_target_exists()`, `check_unknown_mapping_exists()`

### Test Suite
- [ ] `pytest tests/props/db/` passes (core DB tests)
- [ ] `pytest tests/props/grader/` passes (grader tests)
- [ ] `pytest tests/props/prompt_optimize/examples/` passes (stats/pareto examples)
- [ ] `pytest tests/props/` passes with no FK-related failures

### Known Pre-existing Issues (Not Part of This Work)

1. **ScopeMismatch errors** in `test_splits.py`, `test_validation.py` - fixture scope mismatch
2. **InitFailedError** in E2E tests - `current_agent_run_id() is NULL` - RLS context setup issue

## Test Results (Latest Run)
- `PYTEST_TIMEOUT=120 direnv exec . pytest -n 0 -vv tests/props/grader/test_grading_decisions_constraints.py` → **pass** (12 passed, 1 warning)
- `PYTEST_TIMEOUT=120 direnv exec . pytest -n 0 tests/props/db/test_failed_critic_runs_as_zero_recall.py -q` → **pass** (11 passed, 1 warning)
- `direnv exec . pre-commit run --all-files` → **pass**

## Rollback Plan

If issues arise:
1. Revert trigger additions from squashed migration
2. Revert `make_grader_output()` signature to use `tp_count`
3. Run `props db recreate --yes`

## References

- Migration file: `src/adgn/props/db/migrations/versions/20251223000000_schema_squashed.py`
- Test fixtures: `tests/props/conftest.py`
- AGENTS.md: `src/adgn/props/AGENTS.md` (full project context)
- Testing guide: `tests/props/CLAUDE.md`

### Related Plans (incorporated into squashed migration)

These plans document schema changes that were squashed into `20251223000000_schema_squashed.py`:

- `~/.claude/plans/scope-architecture-migration.md` — Scope architecture migration
  - Added `scope_hash`, `scope` JSONB columns to examples/critic_runs
  - Replaced `is_whole_snapshot` with `scope_kind` (computed from `scope->>'kind'`)
  - Updated views: `occurrence_credits`, `aggregated_recall_by_prompt`, `aggregated_recall_by_example`

- `~/.claude/plans/floofy-mixing-kettle.md` — ImprovementRun → unified AgentRun migration
  - Dropped `improvement_runs` table
  - Created `ImprovementTypeConfig` with `allowed_examples` array
  - Created SECURITY DEFINER functions: `is_agent_example_allowed()`, `is_agent_snapshot_allowed()`
  - Updated RLS policies for improvement agent access
