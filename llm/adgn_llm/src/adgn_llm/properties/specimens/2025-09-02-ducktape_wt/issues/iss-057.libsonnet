local I = import '../../specimen_issues.libsonnet';

// iss-057: One-line formatting in wt_server (signatures and initializers)
I.issueOneOccurrence(
  rationale='Remove unnecessary line breaks in function signatures and simple initializers to improve readability and reduce churn in diffs. Suggested edits: one-line initializer `github=ComponentStatus(state=github_state),` and shorten `_handle_ping_request` signature to one line when it fits.',
  properties=['no-extra-linebreaks'],
  filesToRanges={
    'wt/wt/server/wt_server.py': [[1896, 1898], [1926, 1930]],
  },
)
