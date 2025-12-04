local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 342 creates a new registry instance on the fly instead of requiring the caller to pass it as a parameter.
    This violates the DI pattern used elsewhere in the codebase and makes testing harder.
    The registry should be threaded through as a required argument.
  |||,
  filesToRanges={
    'src/adgn/props/grader/grader.py': [[342, 342]],
  },
)
