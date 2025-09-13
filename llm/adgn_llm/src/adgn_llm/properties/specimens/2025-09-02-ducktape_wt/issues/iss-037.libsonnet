local I = import '../../specimen_issues.libsonnet';

// iss-037: Pydantic v2 migration points (multiple occurrences)
I.issueOccurrencesFromLines(
  rationale=|||
    Uses v1-style class Config; switch to `model_config = ConfigDict(...)` (Pydantic v2).
  |||,
  properties=['pydantic-2'],
  linesByFile={
    'wt/wt/shared/github_models.py': [73, 101, 217],
  },
)
