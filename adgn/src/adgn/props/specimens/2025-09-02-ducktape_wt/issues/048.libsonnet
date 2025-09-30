local I = import '../../specimens/lib.libsonnet';

// iss-048: One-off helper used once
I.issueOneOccurrence(
  rationale='`create_shell_script()` is used exactly once; inline at call site (in `run_wt_command`) instead of keeping a one-off helper.',
  // properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/tests/integration/test_shell_integration.py': [[29, 29]],
  },
)
