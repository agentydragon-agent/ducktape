local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 47-48 split the error message across two logger.error calls where a single call with string concatenation would be clearer and more concise. The message parts are always logged together, so they should be combined.
  |||,
  filesToRanges={'adgn/tests/support/assertions.py': [[47, 48]]},
)
