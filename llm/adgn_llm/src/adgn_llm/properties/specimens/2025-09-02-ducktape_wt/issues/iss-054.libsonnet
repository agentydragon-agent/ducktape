local I = import '../../specimen_issues.libsonnet';

// iss-054: format_list_with_more should use a NAMED constant not overridable param
I.issueOneOccurrence(
  rationale='`format_list_with_more` exposes an unused `max_items` parameter; the parameter is never used by callers and should be removed to reduce API surface. Optionally, introduce a named constant (e.g. FILE_LIST_DISPLAY_LIMIT = 3) and reference it internally if a default is needed. Only expose a parameter if callers must vary the value.',
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/client/view_formatter.py': [[37, 37]],
  },
)
