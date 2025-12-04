local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Query (sqlite.py:145-165) uses raw SQL with `text()` instead of SQLAlchemy
    ORM constructs. The function executes a SELECT with GROUP BY and COALESCE
    using string-based column references.

    Problems with raw SQL: not type-safe (columns as strings), not portable
    (SQL syntax varies), hard to maintain (refactoring tools don't track
    renames), poor error messages (runtime vs import time), no IDE navigation.

    Fix: use SQLAlchemy ORM with `session.query(Run.agent_id, func.coalesce(...)).group_by()`.
    Benefits: type-safe references, database portability, refactoring support,
    better errors, IDE navigation.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [145, 165], // Raw SQL instead of ORM for last_activity
    ],
  },
)
