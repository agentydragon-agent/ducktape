local I = import '../../lib.libsonnet';

// Agent.id uses raw str instead of AgentID domain type

I.issue(
  rationale=|||
    Agent.id (models.py:70) uses Mapped[str], but code wraps with AgentID() at
    runtime (sqlite.py:131,147). If SQLAlchemy supports NewType, should declare
    as AgentID to eliminate runtime wrappers.

    Using domain types provides:
    - Type safety: can't mix different ID types
    - Semantic clarity: not just any string, but specific identifier
    - No runtime conversions/validation
    - Clear type contracts in signatures
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [70],
    'adgn/src/adgn/agent/persist/sqlite.py': [131, 147],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/persist/models.py', 'adgn/src/adgn/agent/persist/sqlite.py'],
  ],
)
