local I = import '../../specimen_issues.libsonnet';

// iss-025: Use walrus operator — combine read-and-check
I.issueOccurrencesFromLines(
  rationale='Use walrus to combine read‑and‑check.',
  properties=['walrus'],
  linesByFile={
    'wt/wt/server/wt_server.py': [
      [1482, 1484, 'Use walrus to combine read‑and‑check: `if not (data := await reader.readline()): return`'],
    ],
  },
)
