local I = import '../../specimens/lib.libsonnet';

// iss-039: Function parameter default mismatch with annotation
I.issueOneOccurrence(
  rationale='parameter `error_message: str = None` should be annotated as `str | None` to match the default.',
  // properties=['type-hints'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[72, 72]],
  },
)
