# Specimen-to-Snapshot Migration Plan

## Implementation Status

### Completed

- **Pydantic Models**: `Snapshot`, `Issue`, `FalsePositive` with new occurrence types (`IssueOccurrence.expect_caught_from`, `FalsePositiveOccurrence.relevant_files`)
- **SnapshotSlug NewType**: Defined in `ids.py`
- **Database Schema**: `snapshots`, `issues`, `false_positives` tables with composite PKs and FK relationships
- **Jsonnet Helpers**: New `lib.libsonnet` with 4 helpers (`issue()`, `issueMulti()`, `falsePositive()`, `falsePositiveMulti()`) + auto-inference + validation
- **snapshots.yaml**: Single registry file created; all `manifest.yaml` files deleted
- **Issue Migration**: All 406 files migrated, directory structure flattened (no `issues/`/`false_positives/` subdirs)
- **FilesystemLoader**: Loads snapshots from YAML, issues from Jsonnet, determines TP/FP by output structure
- **DB Sync**: `sync_snapshots_to_db()`, `sync_issues_to_db()`, `db sync` and `db-recreate` CLI commands
- **CLI Snapshot Subcommands**: `snapshot exec`, `snapshot dump`, `snapshot capture-ducktape`, `snapshot-discover`, `snapshot-grade`
- **Filtering Logic**: `should_catch_occurrence()` and `should_show_fp_occurrence()` helpers

### Remaining TODOs

#### Low Priority (Optional Cleanup)

1. **Rename hydrated.py file** (optional)
   - File: `src/adgn/props/specimens/hydrated.py` could be moved to `hydration.py`
   - Class is already renamed: `HydratedSpecimen` → `HydratedSnapshot`
   - Backwards compat alias provided

2. **ORM SnapshotSlug type annotations** (optional)
   - DB models use `String` for slug columns (works fine, NewType is Python-only)
   - Could add type comments for documentation purposes

### Recently Completed

- **SnapshotRegistry**: Renamed from SpecimenRegistry (backwards compat alias provided)
- **HydratedSnapshot**: Renamed from HydratedSpecimen (backwards compat alias provided)
- **SnapshotRecord**: Renamed from SnapshotRecord (backwards compat alias provided)
- **SnapshotIssuesLoadError**: Renamed from SpecimenIssuesLoadError (backwards compat alias provided)
- **snapshot_slug terminology**: All Python code uses `snapshot_slug` instead of `specimen_slug`
- **SnapshotSlug NewType**: Used in `Issue`, `FalsePositive`, `Snapshot` models
- **TrainingExample model**: Created with `get_training_example()`, `get_examples_for_split()`, `get_all_examples()` methods in FilesystemLoader
- **GEPA integration**: Added `load_training_examples()` function for lightweight dataset loading
- **Documentation**: Updated `authoring.md` and `quality-checklist.md` with new terminology and helpers

---

## Background and Rationale

### Problem Statement

Current specimens are **monolithic**: one specimen slug = one training/eval example. Analysis reveals:

- Specimens review multiple independent subsystems (e.g., `2025-11-26-00`: 22 git-commit-ai issues, 19 agent-server issues, 11 mcp issues)
- Issues cluster around specific files (e.g., 17 issues all touch `git_commit_ai/cli.py`)
- Training/eval is slow because we process entire specimens even when testing specific capabilities
- Cannot reuse source code snapshots across different issue sets

**Goals**:
1. Decouple source code snapshots from issue definitions (enable reuse)
2. Enable smaller, focused training examples for faster iteration
3. Explicit catchability semantics per occurrence

### Data-Driven Analysis

Across all 355 issues in existing specimens:

| Files Touched | Count | Percentage | Cumulative |
|--------------|-------|------------|------------|
| 1 file | 269 | **75.8%** | 75.8% |
| 2 files | 48 | 13.5% | 89.3% |
| 3 files | 15 | 4.2% | 93.5% |
| 4 files | 10 | 2.8% | 96.3% |
| 5+ files | 13 | 3.7% | 100.0% |

**Key insight**: **Three-quarters of issues are single-file** - perfect candidates for auto-inference. Multi-file concerns (24.2%) need explicit `expect_caught_from` specification.

### Design Decision: Occurrence-Level `expect_caught_from`

**Why at occurrence level, not issue level**:
- Each occurrence is independent (reviewing file1 catches occurrence1, not occurrence2)
- Natural for duplication (each duplicate is its own occurrence with independent detection scope)
- Clear evaluation: "Did we catch this specific instance?"
- Handles multi-file requirements (some occurrences need multiple files, others don't)

**Semantics** (AND/OR logic):
- Outer set = **alternatives** (OR) - any one of these is sufficient
- Inner set = **required together** (AND) - all files must be reviewed
- Examples:
  - `{{frozenset({'a.py'})}}` - must review a.py
  - `{{frozenset({'a.py'}), frozenset({'b.py'})}}` - can catch from EITHER a.py OR b.py (duplication)
  - `{{frozenset({'a.py', 'b.py'})}}` - must review BOTH a.py AND b.py together
  - `{{frozenset({'a.py'}), frozenset({'b.py', 'c.py'})}}` - catch from a.py alone OR from b.py+c.py together

---

## Architecture Overview

### Class Responsibilities

1. **FilesystemLoader** (`loaders/filesystem.py`)
   - Parses `snapshots.yaml` → `Snapshot` objects
   - Evaluates `*.libsonnet` → `Issue`/`FalsePositive` objects
   - Determines TP/FP by helper used

2. **SnapshotHydrator** (`hydration.py`) [TODO: rename from `specimens/hydrated.py`]
   - Context manager: Snapshot → hydrated directory path
   - Handles bundle extraction, git clone, caching

3. **SQLAlchemy ORM** (`db/models.py`)
   - `Snapshot`, `Issue`, `FalsePositive` tables
   - Query methods: `get()`, `get_by_split()`, `get_for_snapshot()`

4. **Sync Orchestrator** (`db/sync.py`)
   - `sync_snapshots_to_db()`: YAML → DB
   - `sync_issues_to_db()`: Jsonnet → DB

### File Structure

```
specimens/
  snapshots.yaml                  # All snapshots in one file
  lib.libsonnet                   # Jsonnet helpers
  ducktape/
    2025-11-26-00/
      dead-code-cli.libsonnet     # Issues directly in slug dir
      type-confusion-enums.libsonnet
      fp-intentional-duplication.libsonnet  # FPs mixed with TPs
```

### Database Tables

- `snapshots`: slug (PK), split, source (JSONB), bundle (JSONB)
- `issues`: (snapshot_slug, issue_id) composite PK, rationale, occurrences (JSONB)
- `false_positives`: (snapshot_slug, fp_id) composite PK, rationale, occurrences (JSONB)

---

## Jsonnet Helper Reference

### True Positive Helpers

```jsonnet
// Single occurrence (75% of issues)
I.issue(
  rationale='Dead code should be removed',
  filesToRanges={'src/cli.py': [[145, 167]]},
  // expect_caught_from auto-inferred: [['src/cli.py']]
)

// Multi-file requires explicit expect_caught_from
I.issue(
  rationale='Duplicated enum definitions',
  filesToRanges={
    'src/types.py': [[6, 10]],
    'src/persist.py': [[54, 58]],
  },
  expect_caught_from=[
    ['src/types.py'],      // Catch from either
    ['src/persist.py'],
  ],
)

// Multiple occurrences
I.issueMulti(
  rationale='Imperative list building',
  occurrences=[
    {
      files: {'src/agents.py': [[50, 59]]},
      note: 'In _convert_pending_approvals()',
      expect_caught_from: [['src/agents.py']],
    },
    {
      files: {'src/bridge.py': [[64, 108]]},
      note: 'In list_approvals()',
      expect_caught_from: [['src/bridge.py']],
    },
  ],
)
```

### False Positive Helpers

```jsonnet
// Single FP
I.falsePositive(
  rationale='Intentional duplication for visual consistency',
  filesToRanges={
    'src/Button.svelte': [[45, 60]],
    'src/Link.svelte': [[32, 47]],
  },
  // relevant_files auto-inferred from filesToRanges keys
)

// Multiple FP occurrences
I.falsePositiveMulti(
  rationale='Intentional TODO comments in tests',
  occurrences=[
    {
      files: {'tests/test_api.py': [[10, 10]]},
      note: 'Placeholder for future test',
      relevant_files: ['tests/test_api.py'],
    },
  ],
)
```

---

## CLI Commands

### Snapshot Subcommands
```bash
adgn-properties snapshot exec ducktape/2025-11-26-00 -- ls -la
adgn-properties snapshot dump ducktape/2025-11-26-00
adgn-properties snapshot capture-ducktape --slug ducktape/2025-12-01-00
```

### Hyphenated Commands
```bash
adgn-properties snapshot-discover ducktape/2025-11-26-00 --preset max-recall-critic
adgn-properties snapshot-grade <critique-id>
```

### Database Commands
```bash
adgn-properties sync              # Sync snapshots + issues from filesystem
adgn-properties db-recreate       # Drop + recreate + sync
```

### Run Command
```bash
adgn-properties run --snapshot ducktape/2025-11-26-00 --preset max-recall-critic --structured
```
