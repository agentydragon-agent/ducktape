# Examples Table

Training/validation examples define what a critic reviews.

## examples

!psql -c "\d+ examples"

## Example Types

Each example has an `example_kind` field with one of two values:

**Whole snapshot** (`example_kind = 'whole_snapshot'`):
- Critic reviews ALL files in the snapshot
- Used for comprehensive whole-repo evaluation
- Terminal metric for validation
- `files_hash` is NULL

**File set** (`example_kind = 'file_set'`):
- Critic reviews only specific files
- `files` array in scope JSON contains relative paths (e.g., `["src/foo.py", "src/bar.py"]`)
- Used for focused per-file training
- `files_hash` is a hash of the sorted file list

## Querying Examples

```sql
-- All examples for a snapshot
SELECT example_kind, files_hash, scope FROM examples WHERE snapshot_slug = 'ducktape/2025-11-26-00';

-- Whole-snapshot examples only
SELECT * FROM examples WHERE example_kind = 'whole_snapshot';

-- File-set examples only
SELECT * FROM examples WHERE example_kind = 'file_set';

-- Specific example by composite key
SELECT * FROM examples
WHERE snapshot_slug = 'ducktape/2025-11-26-00'
  AND example_kind = 'file_set'
  AND files_hash = 'abc123...';
```

## Example Generation

Examples are auto-generated from `expect_caught_from` in ground truth:
- Each unique trigger set becomes a per-file example
- Plus one full-snapshot example per snapshot
