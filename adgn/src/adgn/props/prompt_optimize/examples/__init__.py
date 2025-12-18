"""Prompt optimizer example scripts.

These examples demonstrate common database queries and workflows for the
prompt optimizer agent. Each file focuses on a specific use case:

- listing.py: List examples/snapshots by split and scope
- prompt_metrics_targeted.py: Prompt metrics via views (targeted mode only)
- prompt_metrics_whole_repo.py: Prompt metrics via SECURITY DEFINER function (whole-repo mode)
- runs.py: Run status, execution traces, failure analysis
- pareto.py: Pareto frontier analysis
- evaluation_pipeline.py: Async run_critic/run_grader pipeline usage

Mode compatibility:
- Targeted mode: Uses views directly (occurrence_credits, aggregated_recall_by_prompt)
  Can see validation example filenames but not ground truth.
- Whole-repo mode: Uses get_validation_run_aggregates() SECURITY DEFINER function.
  Validation examples table is RLS-blocked.
"""
