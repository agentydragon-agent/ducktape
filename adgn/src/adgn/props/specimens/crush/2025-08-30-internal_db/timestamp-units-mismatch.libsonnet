local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Timestamp units are inconsistent across SQL sources, generated sqlc code, and (by extension) calling Go code.

    Findings (evidence excerpts):
    - messages.sql uses microseconds (julianday × 86400000000) for created_at/updated_at.
    - messages.sql.go (generated) still updates updated_at using seconds via strftime('%s','now').
    - files.sql.go uses microseconds for created_at/updated_at in INSERT, diverging from messages.

    Why it matters
    - Delta/watermark queries that rely on created_at/updated_at ordering can break (skips/duplicates, out-of-order).
    - Mixed units undermine tie-breaking semantics in (updated_at, id) ordered scans.

    Acceptance criteria
    - Pick a single unit (prefer microseconds) for all created_at/updated_at writes.
    - Align SQL and regenerate sqlc so generated code matches sources.
    - Re-run ordering/delta queries to confirm monotonic ordering and stable pagination.

    Notes
    - Ordering drift (created_at, rowid) is filed separately; this issue is strictly about unit consistency.
  |||,
  filesToRanges={
    // Microseconds in SQL (messages): INSERT/UPDATE
    'internal/db/sql/messages.sql': [
      [19, 24],  // INSERT ... CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER)
      [31, 33],  // UPDATE ... updated_at = CAST((julianday('now') - 2440587.5) * 86400000000 AS INTEGER)
    ],

    // Seconds in generated code (messages): UPDATE uses strftime('%s','now')
    'internal/db/messages.sql.go': [[260, 270]],

    // Microseconds in generated code (files): INSERT values
    'internal/db/files.sql.go': [[18, 24]],

    // Migrations (context of unit changes)
    'internal/db/migrations/20250424200609_initial.sql': null,
    'internal/db/migrations/20250829011000_use_microsecond_timestamps.sql': null,
  },
  expect_caught_from=[['internal/db/sql/messages.sql', 'internal/db/messages.sql.go'], ['internal/db/files.sql.go']],
)
