local I = import '../../specimen_issues.libsonnet';

// iss-053: FILE_DISPLAY_LIMIT is unreferenced and in the wrong layer
I.issueOneOccurrence(
  rationale='`FILE_DISPLAY_LIMIT` is unreferenced in shared/constants.py and appears to be a client-side display constant; delete it from shared. FILE_DISPLAY_LIMIT = 10 is unreferenced; remove it from shared/constants.py.',
  properties=['no-dead-code'],
  filesToRanges={
    'wt/wt/shared/constants.py': [[12, 12]],
  },
)
