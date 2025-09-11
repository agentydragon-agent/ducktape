local I = import '../../specimen_issues.libsonnet';

// iss-070: Use timedelta or explicit unit suffixes for timing params
I.issueOccurrencesFromLines(
  id='iss-070',
  rationale='Timing parameters should use rich time types (datetime.timedelta) or explicit unit-suffixed numeric names to avoid ambiguity and improve readability.',
  properties=['time'],
  linesByFile={
    'wt/wt/server/wt_server.py': [[147,153]],
    'wt/tests/test_utils.py': [[6,6], [33,33]],
  },
)
