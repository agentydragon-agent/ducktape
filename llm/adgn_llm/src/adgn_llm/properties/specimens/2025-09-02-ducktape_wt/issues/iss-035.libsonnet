local I = import '../../specimen_issues.libsonnet';

// iss-035: Use str.removeprefix for fixed affix removal
I.issueOccurrencesFromLines(
  rationale='Use str.removeprefix("wtid:") for fixed prefix removal instead of slicing (e.g., `wtid[5:]`). This is clearer, avoids a magic constant, and is idiomatic in modern Python.',
  properties=['str-affixes'],
  linesByFile={
    'wt/wt/shared/protocol.py': [[29, 31]],
  },
)
