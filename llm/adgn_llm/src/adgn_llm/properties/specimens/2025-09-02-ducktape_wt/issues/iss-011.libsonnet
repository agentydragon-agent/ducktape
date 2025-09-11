local I = import '../../specimen_issues.libsonnet';

// iss-011: Do not catch broad OSErrors for fd3 probe
I.issueOneOccurrence(
  id='iss-011',
  rationale= |||
    Do not catch case of "fd3 not open/not present" by catching arbitrary OSErrors. In this case,
    positive and explicit probe is not too difficult so should be used: probe fd3 with fcntl
    (F_GETFD/F_GETFL) to verify it exists and is opened for writing.
  |||,
  properties=[],
  filesToRanges={
    'wt/wt/client/shell_utils.py': [[6,15]],
  },
)
