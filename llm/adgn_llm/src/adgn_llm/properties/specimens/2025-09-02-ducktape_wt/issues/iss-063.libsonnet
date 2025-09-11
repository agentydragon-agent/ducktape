local I = import '../../specimen_issues.libsonnet';

// iss-063: Remove docstrings that restate obvious truths for boolean properties
I.issueOneOccurrence(
  id='iss-063',
  rationale='properties `has_untracked_files` and `has_dirty_files` have docstrings that restate the obvious; remove or replace with a one-line phrase if needed to explain non-obvious behavior.',
  properties=['no-useless-docs'],
  gap_note='GAP: When a type has a single Falsey/Truthy member prefer truthiness (e.g., `if array:`) where readable; avoid `(x or 0) > 0` style checks.',
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[119,127], [126,130]],
  },
)
