local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 131-132 use min(1.0, cov.recall_credit) when summing recall credits. The field is already
    capped at 1.0 by Pydantic's RatioFloat constraint (Field(ge=0.0, le=1.0)), making min() redundant.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/grader/grader.py': [[131, 132]],
  },
)
