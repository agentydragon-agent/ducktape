local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Multiple consecutive empty lines or strategically poor empty line placement that reduces readability.
    Lines 328-348 have excessive empty lines interspersed with useless comments.
  |||,
  filesToRanges={
    'src/adgn/props/grader/grader.py': [[328, 348]],
  },
)
