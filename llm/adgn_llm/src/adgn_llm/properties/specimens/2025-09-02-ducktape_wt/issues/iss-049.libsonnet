local I = import '../../specimen_issues.libsonnet';

// iss-049: Duplicate daemon_cleanup helper defined twice
I.issueOneOccurrence(
  id='iss-049',
  rationale='Duplicate `daemon_cleanup` helper defined twice (one copy at 216–222); extract a single helper and reuse.',
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/tests/integration/test_shell_integration.py': [[216,222]],
  },
)
