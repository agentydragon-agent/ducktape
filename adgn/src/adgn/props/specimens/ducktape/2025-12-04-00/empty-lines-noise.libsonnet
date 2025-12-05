local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Unnecessary empty lines that add no value to code organization. These lines should be deleted to reduce vertical space without losing readability.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/grader/grader.py': [290, 308, 311, 318],
  },
)
