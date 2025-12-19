"""Prompt optimizer example scripts.

These examples demonstrate common database queries and workflows for the
prompt optimizer agent. Each file focuses on a specific use case:

- listing.py: List examples/snapshots by split and scope
- prompt_metrics_targeted.py: Prompt metrics via views (targeted mode only)
- prompt_metrics_whole_repo.py: Prompt metrics via SQL function (whole-repo mode)
- pareto.py: Pareto frontier analysis
- evaluation_pipeline.py: Async run_critic/run_grader pipeline usage

Note: runs.py moved to adgn.props.examples (shared across agents)

Mode compatibility:
- Targeted mode: Uses views directly (occurrence_credits, aggregated_recall_by_prompt)
  Can see validation example filenames but not ground truth.
- Whole-repo mode: Uses SQL `SELECT * FROM get_validation_run_aggregates()` function.
  IMPORTANT: get_validation_run_aggregates() is a PostgreSQL function (NOT Python).
  Call it via SQL, not via Python import. There is no Python export.
  Validation examples table is RLS-blocked.
"""
