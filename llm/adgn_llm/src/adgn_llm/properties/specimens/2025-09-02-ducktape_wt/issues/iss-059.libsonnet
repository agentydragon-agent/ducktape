local I = import '../../specimen_issues.libsonnet';

// iss-059: Inline one-off `all_args` in CLI
I.issueOneOccurrence(
  id='iss-059',
  rationale='`all_args` is a one-off variable used only to combine two arg lists; inline the combined args directly in the loop to reduce noise and a one-off variable. Suggested change: `for arg in [*args, *ctx.args]: ...`.',
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/cli.py': [[137,143]],
  },
)

