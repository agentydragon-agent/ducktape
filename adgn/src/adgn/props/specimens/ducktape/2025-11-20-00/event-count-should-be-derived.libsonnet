local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Run model stores event_count: Mapped[int] (models.py:65) that duplicates information
    already available from the events relationship.

    event_count is manually incremented on every event insert (sqlite.py:389):
    update(Run).where(Run.id == str(run_id)).values(event_count=Run.event_count + 1)

    This is:
    - Redundant: count is derivable from len(run.events) or COUNT query
    - Error-prone: risks desync if increments are missed or duplicated
    - Additional write overhead on every event

    Should remove event_count field and compute when needed:
    - For queries: SELECT COUNT(*) FROM events WHERE run_id = ?
    - For loaded objects: len(run.events)
    - For aggregation: Use SQLAlchemy func.count()

    Storage denormalization only justified for performance-critical paths, not evident here.
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [
      65,           // event_count: Mapped[int] field definition
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      342,          // event_count=0 in Run creation
      389,          // Manual increment on event insert
      415,          // event_count usage in list_runs
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/persist/models.py', 'adgn/src/adgn/agent/persist/sqlite.py'],
  ],
)
