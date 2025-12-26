"""Shared example scripts for querying the properties evaluation database.

These examples are used by multiple agents (prompt optimizer, prompt improver, etc.)
in their bootstrap phase to demonstrate database query patterns.

Available examples:
- listing.py: List examples and snapshots by split and scope
- pareto.py: Pareto frontier analysis (which definitions win on which examples)
- definition_stats_targeted.py: Definition performance stats for targeted mode
- definition_stats_whole_repo.py: Definition performance stats for whole-repo mode
- evaluation_pipeline.py: Async evaluation pipeline using run_critic/run_grader
- rollout_analysis.py: Query builders and display functions for execution traces
- working_with_examples.py: Working with training examples and queries
- mcp_http_client_example.py: Example MCP HTTP client usage
"""
