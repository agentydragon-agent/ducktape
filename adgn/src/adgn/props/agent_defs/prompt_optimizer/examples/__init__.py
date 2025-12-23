"""Prompt optimizer example scripts.

These examples demonstrate common database queries and workflows for the
prompt optimizer agent. Each file focuses on a specific use case:

- listing.py: List examples/snapshots by split and scope
- definition_stats_targeted.py: Definition statistics via views (targeted mode only)
- definition_stats_whole_repo.py: Definition statistics via SQL function (whole-repo mode)
- pareto.py: Pareto frontier analysis
- evaluation_pipeline.py: Async run_critic/run_grader pipeline usage
- rollout_analysis.py: Execution trace analysis (query builders and display functions)

Mode compatibility:
- Targeted mode: Uses views directly (occurrence_credits, aggregated_recall_by_definition)
  Can see validation example filenames but not ground truth.
- Whole-repo mode: Uses SQL `SELECT * FROM get_validation_full_snapshot_aggregates()` function.
  IMPORTANT: get_validation_full_snapshot_aggregates() is a PostgreSQL function (NOT Python).
  Call it via SQL, not via Python import. There is no Python export.
  Validation examples table is RLS-blocked.
"""
