local I = import '../../specimens/lib.libsonnet';

// iss-022: Minimize nesting — remove redundant inner guard under while
I.issueOccurrencesFromLines(
  rationale='Inner if self.is_running under a while self.is_running loop is redundant; flatten the loop body to reduce nesting.',
  // properties=['minimize-nesting'],
  linesByFile={
    'wt/wt/server/wt_server.py': [
      [257, 275],
    ],
  },
)
