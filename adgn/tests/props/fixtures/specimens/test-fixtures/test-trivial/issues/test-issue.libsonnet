local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Test issue for integration testing.
    This is a minimal issue to satisfy specimen validation.
  |||,
  filesToRanges={
    'subtract.py': [[10, 15]],
  },
)
