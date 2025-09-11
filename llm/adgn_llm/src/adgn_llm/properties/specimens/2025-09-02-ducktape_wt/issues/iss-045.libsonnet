local I = import '../../specimen_issues.libsonnet';

// iss-045: _safe_get_repository_state masks missing/invalid state
I.issueOneOccurrence(
  id='iss-045',
  rationale='`_safe_get_repository_state` treats missing/invalid state as NORMAL. Do not mask errors as a valid state; raise or return an error.',
  properties=['scoped-try-except'],
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[338, 355]],
  },
)
