local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 273, 276, 284-285 in the run_grader tool docstring claim the grader computes "precision" and "metrics" (true_positives/false_positives/false_negatives) and that these are available as grade.precision and grade.metrics in the output. However, the GradeSubmitInput model (grader/models.py:360-485) does not have precision or metrics fields.

    The actual output structure is:
    - grade.recall (the only computed metric)
    - grade.reported_issue_ratios (with tp/fp/unlabeled breakdown)
    - grade.canonical_tp_coverage
    - grade.canonical_fp_coverage
    - grade.novel_critique_issues
    - grade.summary

    The docstring should be corrected to reflect the actual model fields rather than mentioning non-existent precision and metrics fields.
  |||,
  filesToRanges={'adgn/src/adgn/props/prompt_optimizer.py': [[273, 276], [284, 285]]},
)
