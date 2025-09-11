local I = import '../../specimen_issues.libsonnet';

// iss-071: Convert inline comments in DebouncedGitHubRefresh.__init__ into a proper Args docstring
I.issueOneOccurrence(
  id='iss-071',
  rationale='Replace inline "Configurable timing" / "State tracking" comments and trailing parameter comments in DebouncedGitHubRefresh.__init__ with a proper Args docstring. Preserve any useful explanatory details in the docstring (not comments) so the information remains discoverable and testable.',
  properties=['no-useless-docs'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[147,167]],
  },
)
