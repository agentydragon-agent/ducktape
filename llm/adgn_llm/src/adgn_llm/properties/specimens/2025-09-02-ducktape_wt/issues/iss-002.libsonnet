local I = import '../../specimen_issues.libsonnet';

  // iss-002: Use StrEnum for string-valued enums
  I.issueOccurrencesFromLines(
    id='iss-002',
    rationale= |||
  Use StrEnum for closed sets of string domain values so they behave as plain strings at boundaries
  (serialization/APIs/JSON) without forcing callers to unwrap .value, while still enforcing the
  allowed set.
|||,

    properties=['strenum'],
    linesByFile={
      'wt/wt/shared/github_models.py': [[13, 18], [49, 52], [60, 62]],
      'wt/wt/shared/configuration.py': [[21, 27]],
      'wt/wt/shared/protocol.py': [[34, 40], [317, 322], [435, 441], [443, 449]],
      'wt/wt/server/gitstatusd_client.py': [[29, 43]],
      'wt/wt/server/copy_strategies.py': [[18, 23]],
    },
  )
