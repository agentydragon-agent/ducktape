# Examples Table

Training/validation examples define what a critic reviews.

## examples

!psql -c "\d+ examples"

## Scope Types

Each example has a `scope` JSON field with one of two kinds:

**Entire snapshot** (`kind: "entire_snapshot"`):
- Critic reviews ALL files in the snapshot
- Used for comprehensive whole-repo evaluation
- Terminal metric for validation

**Specific files** (`kind: "specific_files"`):
- Critic reviews only the listed files
- `files` array contains relative paths (e.g., `["src/foo.py", "src/bar.py"]`)
- Used for focused per-file training

## Querying Examples

```sql
-- All examples for a snapshot
SELECT scope_hash, scope FROM examples WHERE snapshot_slug = 'ducktape/2025-11-26-00';

-- Full-snapshot examples only
SELECT * FROM examples WHERE scope->>'kind' = 'entire_snapshot';

-- Per-file examples
SELECT * FROM examples WHERE scope->>'kind' = 'specific_files';
```

## Example Generation

Examples are auto-generated from `expect_caught_from` in ground truth:
- Each unique trigger set becomes a per-file example
- Plus one full-snapshot example per snapshot
