local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Ordering drift: SQL orders ListMessagesBySession by created_at, id (messages.sql lines 6–11),
    but generated code orders by created_at, rowid (messages.sql.go lines ~105–113). This changes
    tie-breaker semantics and can cause inconsistent ordering.

    Minimal fix: align SQL and regenerate sqlc; prefer explicit id ordering.
  |||,
  filesToRanges={
    'internal/db/sql/messages.sql': [[6, 11]],
    'internal/db/messages.sql.go': [[105, 113]],
  },
  expect_caught_from=[
    ['internal/db/sql/messages.sql'],
    ['internal/db/messages.sql.go'],
  ],
)
