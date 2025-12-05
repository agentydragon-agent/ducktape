local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The code logs the length of the initial prompt instead of the prompt itself.
    Since the prompt is not private and is very short, it should be logged directly for debugging purposes.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/grader/grader.py': [[205, 207]],
  },
)
