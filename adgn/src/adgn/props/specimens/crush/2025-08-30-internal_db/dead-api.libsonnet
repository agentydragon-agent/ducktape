local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Dead API: ListLatestSessionFiles is defined and wired through the DB layer but has no production callers; it is referenced only by a test fake.

    Summary
    - The history service interface exposes ListLatestSessionFiles and forwards to the DB query.
    - The DB layer declares, prepares, and exposes the query.
    - No runtime code consumes it; a test fake implements it by delegating to ListBySession, masking drift.

    Why this matters
    - Unused API surfaces can drift from intended semantics (and already do — global per-path grouping instead of per-(session,path)).
    - Dead code increases maintenance burden and creates footguns for future callers.

    Acceptance criteria
    - Either remove the API and associated SQL wiring, or add a real caller and correct the query semantics to per-(session_id,path) latest.
  |||,
  filesToRanges={
    // History service interface + implementation invoking the dead API
    'internal/history/file.go': [[35, 36], [161, 171]],

    // DB layer: declaration/prepare/query text and wrapper
    'internal/db/querier.go': [[26, 26]],
    'internal/db/db.go': [[69, 70]],
    'internal/db/files.sql.go': [[206, 216], [218, 220]],

    // Test-only usage (fake)
    'internal/llm/tools/multiedit_test.go': [[92, 93]],
  },
  expect_caught_from=[['internal/history/file.go'], ['internal/db/querier.go'], ['internal/db/db.go'], ['internal/db/files.sql.go']],
)
