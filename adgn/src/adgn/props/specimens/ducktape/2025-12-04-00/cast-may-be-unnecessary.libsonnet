local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 307 uses cast(GradeValidationContext, ctx) after already checking isinstance.
    After the isinstance check on line 305, mypy should already know the type.
    The cast may be unnecessary redundancy.
  |||,
  filesToRanges={
    'adgn/src/adgn/props/grader/models.py': [[307, 307]],
  },
)
