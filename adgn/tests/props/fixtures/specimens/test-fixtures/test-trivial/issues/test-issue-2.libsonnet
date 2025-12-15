local I = import '../../../lib.libsonnet';

I.issue(
  rationale=|||
    Second test issue for integration testing.
    This ensures the snapshot has multiple files with issues.
  |||,
  filesToRanges={
    'add.py': [[4, 6]],
  },
  expect_caught_from=[['add.py']],
)
