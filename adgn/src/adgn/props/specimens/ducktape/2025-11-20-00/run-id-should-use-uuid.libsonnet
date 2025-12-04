local I = import '../../lib.libsonnet';

// Run.id uses Mapped[str] but domain code uses UUID

I.issue(
  rationale=|||
    Run.id (models.py:57) uses Mapped[str] in model, but domain code uses UUID.
    Creates constant str(run_id) conversions (sqlite.py:378,389). SQLAlchemy
    supports UUID types that handle serialization automatically.

    Using domain types provides:
    - Type safety: can't mix different ID types
    - Semantic clarity: not just any string, but specific identifier
    - No runtime conversions/validation
    - Clear type contracts in signatures
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/models.py': [57],
    'adgn/src/adgn/agent/persist/sqlite.py': [378, 389],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/persist/models.py', 'adgn/src/adgn/agent/persist/sqlite.py'],
  ],
)
