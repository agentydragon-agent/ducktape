local I = import '../../specimens/lib.libsonnet';

// iss-042: Unused fixture in tests/conftest.py
I.issueOneOccurrence(
  rationale='`empty_worktree_status()` is unused; delete the fixture.',
  // properties=['no-dead-code'],
  filesToRanges={
    'wt/tests/conftest.py': [[122, 124]],
  },
)
