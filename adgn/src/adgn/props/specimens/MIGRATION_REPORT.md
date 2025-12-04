# Specimen-to-Snapshot Migration Report

## Summary

Migration completed on 2025-12-04.

## Definition of Done (DoD)

### Completed
- [x] All Jsonnet files pass validation (406/406)
- [x] Directory structure flattened (no `issues/` or `false_positives/` subdirs)
- [x] All files use new helpers (`I.issue`, `I.issueMulti`, `I.falsePositive`, `I.falsePositiveMulti`)
- [x] All imports at the top of each file (standard Jsonnet style: `local I = import '../../lib.libsonnet';`)
- [x] All multi-file issues have `expect_caught_from` specified
- [x] Import paths corrected to `../../lib.libsonnet` for 2-level deep files
- [x] **Snapshot auto-derived from path**: Removed `snapshot` parameter from Jsonnet helpers and all files. Snapshot slug is now derived at Python loader level from file path
- [x] **SnapshotSlug NewType**: Converted from `TypeAlias` to `NewType` in `ids.py` for compile-time type safety
- [x] **ORM SnapshotSlug typing**: All ORM method signatures in `db/models.py` use `SnapshotSlug` type with `str()` casting at SQLAlchemy comparison points. Tables: `Snapshot`, `TruePositive`, `FalsePositive`. Column definitions remain `Mapped[str]` (correct for SQLAlchemy).
- [x] **Pydantic SnapshotSlug typing**: `TruePositive.snapshot_slug` and `FalsePositive.snapshot_slug` use `SnapshotSlug` NewType
- [x] **PydanticColumn for Snapshot fields**: `Snapshot.source` (Source union) and `Snapshot.bundle` (BundleFilter) use `PydanticColumn` for automatic Pydantic serialization/deserialization

### Remaining (Technical Debt)
None - all migration tasks completed as of 2025-12-04.

## expect_caught_from: Semantics and Reasoning

### What is `expect_caught_from`?

The `expect_caught_from` field specifies the **minimal file sets required to detect an issue**. It uses AND/OR logic:

- **Outer list = OR**: Any of these file sets is sufficient to detect the issue
- **Inner list = AND**: All files in the set must be reviewed together

### Notation

```jsonnet
expect_caught_from=[
  ['file_a.py'],           // Detectable from file_a alone
  ['file_b.py'],           // OR detectable from file_b alone
  ['file_c.py', 'file_d.py'],  // OR requires BOTH file_c AND file_d together
]
```

### Decision Framework

When setting `expect_caught_from`, we applied these rules:

#### 1. Independent Occurrences (Most Common)
When the same issue pattern appears independently in multiple files, each file is listed separately:

```jsonnet
// Each file has a copy-paste of the same anti-pattern
expect_caught_from=[['file1.py'], ['file2.py'], ['file3.py']]
```

**Reasoning**: A critic reviewing any single file can identify the issue without seeing the others.

#### 2. Comparison Required (Duplication/Drift)
When detecting the issue requires comparing two or more files:

```jsonnet
// Ordering mismatch between SQL schema and generated code
expect_caught_from=[['messages.sql', 'messages.sql.go']]
```

**Reasoning**: The issue (drift between SQL and generated Go) can only be detected by seeing both files together.

#### 3. Interface vs Implementation
When an issue spans interface definitions and implementations:

```jsonnet
// Dead API: interface declared but no callers
expect_caught_from=[
  ['internal/history/file.go'],  // Interface definition
  ['internal/db/querier.go'],    // DB declaration
  ['internal/db/files.sql.go'],  // Query implementation
]
```

**Reasoning**: The issue (unused API) can be identified from any of these locations - each reveals "this exists but isn't called".

#### 4. Single Source of Truth
When only one file definitively shows the issue:

```jsonnet
// Config field name doesn't match JSON tag
expect_caught_from=[['config.go']]
```

**Reasoning**: Only the config definition file reveals the mismatch; other files may use the API but can't diagnose the root cause.

### Examples from Migration

| Issue Type | expect_caught_from | Reasoning |
|------------|-------------------|-----------|
| Dead code in single file | `[['watcher.go']]` | Unreachable branch visible in one file |
| Duplicated logic across files | `[['file1.go'], ['file2.go']]` | Same pattern independently in each |
| Schema/code drift | `[['schema.sql', 'model.go']]` | Requires comparison |
| Unused API | Multiple alternatives | Visible from definition OR any usage site |

### Validation

The grader uses `expect_caught_from` to determine if a critic "should have" caught an issue:

```python
def should_catch_occurrence(occ: IssueOccurrence, reviewed_files: set[Path]) -> bool:
    """Returns True if any alternative file set is a subset of reviewed files."""
    return any(alt.issubset(reviewed_files) for alt in occ.expect_caught_from)
```

If a critic reviewed files that include any complete file set from `expect_caught_from` but didn't report the issue, it's a false negative.

## Statistics

| Type | Count |
|------|-------|
| Total issue files | 406 |
| Single-occurrence issues (`I.issue()`) | 367 |
| Multi-occurrence issues (`I.issueMulti()`) | 33 |
| False positives (`I.falsePositive()`) | 6 |

## Changes Applied

1. **Directory Structure**: Flattened from `{snapshot}/issues/` and `{snapshot}/false_positives/` to `{snapshot}/` (files at snapshot root)

2. **File Format**: All files now use the new Jsonnet helpers:
   - `I.issue(snapshot, rationale, filesToRanges, expect_caught_from?)` - single occurrence
   - `I.issueMulti(snapshot, rationale, occurrences)` - multiple occurrences
   - `I.falsePositive(snapshot, rationale, filesToRanges, relevant_files?)` - single FP
   - `I.falsePositiveMulti(snapshot, rationale, occurrences)` - multiple FPs

3. **New Required Fields**:
   - `snapshot`: Snapshot slug (e.g., 'ducktape/2025-11-26-00')
   - `expect_caught_from`: For true positives, specifies minimal file sets for detection

4. **Import Paths**: Updated to `../../lib.libsonnet` (2 levels up from `{repo}/{version}/`)

## Snapshots Migrated

- `crush/2025-08-30-internal_db`
- `ducktape/2025-09-03-00`
- `ducktape/2025-11-20-00`
- `ducktape/2025-11-20-01`
- `ducktape/2025-11-21-00`
- `ducktape/2025-11-22-00`
- `ducktape/2025-11-22-01`
- `ducktape/2025-11-22-02`
- `ducktape/2025-11-26-00`
- `misc/2025-08-29-pyright_watch_report`

## Deleted Files

- All `manifest.yaml` files (replaced by `snapshots.yaml`)
- Subdirectories: `issues/` and `false_positives/` (files moved to parent)

## Manual Review Files (33 total)

These files with multiple occurrences were manually reviewed and converted to `I.issueMulti()` with explicit `expect_caught_from` for each occurrence:

### crush/2025-08-30-internal_db (16 files)
- ambiguous-id-params.libsonnet
- config-nil-chains.libsonnet
- control-flow-complexity.libsonnet
- dead-code.libsonnet
- digit-width-duplication.libsonnet
- excessive-nesting.libsonnet
- facade-law-of-demeter.libsonnet
- hardcoded-timeouts.libsonnet
- one-off-vars.libsonnet
- path-schema-docs-mismatch.libsonnet
- permission-flow-dup.libsonnet
- renderer-guard-clauses.libsonnet
- response-wrap-duplication.libsonnet
- terse-var-names.libsonnet
- timestamp-type-inconsistency.libsonnet
- utf8-typo.libsonnet

### ducktape/2025-09-03-00 (9 files)
- exceptions-for-control-flow.libsonnet
- imports-module-level.libsonnet
- pathlib-direct-pass.libsonnet
- pep604-builtin-generics.libsonnet
- prefer-pathlib-apis.libsonnet
- remove-shebangs-libs.libsonnet
- sandbox-silent-fallback.libsonnet
- scoped-try-except-swallow.libsonnet
- tighten-optional-params.libsonnet

### ducktape/2025-11-20-00 (1 file)
- registry-get-missing.libsonnet

### ducktape/2025-11-22-00 (2 files)
- ui-imports-not-at-top.libsonnet
- unimplemented-websocket.libsonnet

### ducktape/2025-11-22-02 (3 files)
- historical-comments.libsonnet
- obvious-comments.libsonnet
- one-off-variables.libsonnet

### ducktape/2025-11-26-00 (2 files)
- inline-intermediate-variables.libsonnet
- useless-docstrings.libsonnet
