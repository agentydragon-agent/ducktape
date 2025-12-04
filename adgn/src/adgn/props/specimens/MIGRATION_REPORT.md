# Specimen-to-Snapshot Migration Report

## Summary

Migration completed on 2025-12-04.

### Statistics

| Type | Count |
|------|-------|
| Total issue files | 406 |
| Single-occurrence issues (`I.issue()`) | 367 |
| Multi-occurrence issues (`I.issueMulti()`) | 33 |
| False positives (`I.falsePositive()`) | 6 |

### Changes Applied

1. **Directory Structure**: Flattened from `{snapshot}/issues/` and `{snapshot}/false_positives/` to `{snapshot}/` (files at snapshot root)

2. **File Format**: All files now use the new Jsonnet helpers:
   - `I.issue(snapshot, rationale, filesToRanges, expect_caught_from?)` - single occurrence
   - `I.issueMulti(snapshot, rationale, occurrences)` - multiple occurrences
   - `I.falsePositive(snapshot, rationale, filesToRanges, relevant_files?)` - single FP
   - `I.falsePositiveMulti(snapshot, rationale, occurrences)` - multiple FPs

3. **New Required Fields**:
   - `snapshot`: Snapshot slug (e.g., 'ducktape/2025-11-26-00')
   - `expect_caught_from`: For true positives, specifies minimal file sets for detection

4. **Import Paths**: Updated to `../lib.libsonnet`

### Snapshots Migrated

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

### Deleted Files

- All `manifest.yaml` files (replaced by `snapshots.yaml`)
- Subdirectories: `issues/` and `false_positives/` (files moved to parent)

### Manual Review Files (33 total)

These files with multiple occurrences were manually reviewed and converted to `I.issueMulti()` with explicit `expect_caught_from` for each occurrence:

#### crush/2025-08-30-internal_db (16 files)
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

#### ducktape/2025-09-03-00 (9 files)
- exceptions-for-control-flow.libsonnet
- imports-module-level.libsonnet
- pathlib-direct-pass.libsonnet
- pep604-builtin-generics.libsonnet
- prefer-pathlib-apis.libsonnet
- remove-shebangs-libs.libsonnet
- sandbox-silent-fallback.libsonnet
- scoped-try-except-swallow.libsonnet
- tighten-optional-params.libsonnet

#### ducktape/2025-11-20-00 (1 file)
- registry-get-missing.libsonnet

#### ducktape/2025-11-22-00 (2 files)
- ui-imports-not-at-top.libsonnet
- unimplemented-websocket.libsonnet

#### ducktape/2025-11-22-02 (3 files)
- historical-comments.libsonnet
- obvious-comments.libsonnet
- one-off-variables.libsonnet

#### ducktape/2025-11-26-00 (2 files)
- inline-intermediate-variables.libsonnet
- useless-docstrings.libsonnet
