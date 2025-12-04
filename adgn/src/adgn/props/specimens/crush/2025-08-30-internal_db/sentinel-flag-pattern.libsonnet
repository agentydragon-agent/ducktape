local I = import '../../lib.libsonnet';


I.issue(
  rationale='ArgumentsBlocker in internal/shell/shell.go uses a sentinel flag inside an inner loop to decide post-loop behavior. Prefer a labeled continue to skip to the next outer iteration and keep the happy-path less indented.',
  filesToRanges={
    'internal/shell/shell.go': [[183, 201]],
  },
)
