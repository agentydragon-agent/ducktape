"""Restore recall_by_example view and add comments to agent-facing views.

Revision ID: 20251226000002
Revises: 20251226000001
Create Date: 2025-12-26

The recall_by_example view was dropped by CASCADE in 20251226000000 and not recreated.
This migration restores it and adds COMMENT ON statements to views that agents see
via describe_relation() in their system prompts.
"""

from alembic import op

revision = "20251226000002"
down_revision = "20251226000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Restore recall_by_example view (aggregates across definitions)
    op.execute("""
        CREATE VIEW recall_by_example AS
        WITH raw_stats AS (
            SELECT
                rbde.snapshot_slug,
                rbde.example_kind,
                rbde.files_hash,
                rbde.split,
                MAX(rbde.n_catchable_occurrences)::integer AS n_catchable_occurrences,
                rbde.critic_model,
                SUM(rbde.n_runs)::integer AS n_runs,
                agg_status_counts(array_agg(rbde.status_counts)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((rbde.credit_stats).mean, 0.0)
                )) AS credit_stats
            FROM recall_by_definition_example rbde
            GROUP BY rbde.snapshot_slug, rbde.example_kind, rbde.files_hash, rbde.split, rbde.critic_model
        )
        SELECT
            snapshot_slug, example_kind, files_hash, split,
            n_catchable_occurrences, critic_model, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, n_catchable_occurrences) AS recall_stats
        FROM raw_stats
    """)

    # Grant access
    op.execute("GRANT SELECT ON TABLE recall_by_example TO agent_base")

    # Add comments to agent-facing views
    # These comments appear in psql \d+ output, shown to agents via describe_relation()
    # Include which agent kinds find each view useful

    # Recall views
    op.execute("""
        COMMENT ON VIEW recall_by_run IS
        'Per-run recall statistics. Joins critic runs with grading results.
Columns: snapshot, example (kind+files_hash), split, definition, model, status, credit_stats, recall_stats.

RLS: Inherits from agent_runs, grading_decisions. Prompt optimizer sees TRAIN only.

USEFUL FOR: Prompt optimizer, improvement agent.
- Debug individual runs (why did this run fail?)
- Find runs to retry or analyze
- Compare runs across same definition'
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_example IS
        'Recall aggregated by (definition, example). Stats across multiple runs of same definition on same example.
Key columns: n_runs, status_counts, credit_stats (raw credits), recall_stats (credit/catchable).

RLS: Inherits from recall_by_run. Prompt optimizer sees TRAIN split only.

USEFUL FOR: Prompt optimizer, improvement agent.
- Compare definition performance on specific examples
- Find hard examples for a given definition
- Identify which examples need more attention'
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_split_kind IS
        'Recall aggregated by (definition, split, example_kind). Highest-level summary per definition.
Key columns: n_examples, n_runs, recall_stats with UCB/LCB confidence intervals.

RLS: Returns all splits (TRAIN/VALID/TEST) but inherits RLS from underlying tables.
Prompt optimizer sees all splits because this view is the leaderboard (public summary).

USEFUL FOR: Prompt optimizer (primary metric view).
- Leaderboard: compare definitions by LCB
- Train vs valid comparison (overfitting check)
- n_examples < 5 warning: small sample size, high variance'
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_example IS
        'Recall aggregated by example (across all definitions). Shows per-example difficulty.
Groups by (snapshot, example_kind, files_hash, split, model).

RLS: Inherits from recall_by_definition_example. All splits visible for aggregate metrics.

USEFUL FOR: Prompt optimizer, improvement agent.
- Find hard examples (low recall across all definitions)
- Prioritize which examples to focus improvement efforts on
- Compare example difficulty across splits'
    """)

    # Occurrence views
    op.execute("""
        COMMENT ON VIEW occurrence_credits IS
        'Per-occurrence credit from grading. Base view for computing recall.
Each row = one catchable TP occurrence with its found_credit (0-1).
Sum(found_credit)/count(*) = occurrence-weighted recall.

RLS: CRITICAL - prompt optimizer sees TRAIN split only. VALID/TEST filtered by RLS
on underlying grading_decisions. Prevents overfitting to validation data.

USEFUL FOR: Prompt optimizer (TRAIN split only).
- Analyze which specific occurrences are being missed
- Debug why certain issues are not being caught'
    """)

    op.execute("""
        COMMENT ON VIEW occurrence_statistics IS
        'Aggregate statistics per occurrence across all runs.

RLS: Inherits from occurrence_credits. Prompt optimizer sees TRAIN split only.

USEFUL FOR: Prompt optimizer, improvement agent, clustering agent.
- Find consistently-missed occurrences (low hit rate across runs)
- Identify occurrence patterns that need prompt improvements
- Clustering: analyze which occurrences produce many unknowns'
    """)

    # Other views
    op.execute("""
        COMMENT ON VIEW examples IS
        'Training/validation examples derived from snapshots and file_sets.
Two kinds: whole_snapshot (review all files) or file_set (review specific files).
n_catchable_occurrences = number of TP occurrences catchable from this scope.

RLS: Inherits from snapshots. In whole-repo mode, prompt optimizer sees TRAIN split only.
In targeted mode, all splits visible (filenames only, not ground truth).

USEFUL FOR: All agent types.
- Critic: know what scope to review
- Prompt optimizer: select examples for evaluation
- Improvement agent: select examples by difficulty (start with small n_catchable)'
    """)

    op.execute("""
        COMMENT ON TABLE reported_issues IS
        'Issues reported by critic agents. Each issue has a rationale and one or more occurrences.
Linked to agent_runs via agent_run_id. Occurrences in reported_issue_occurrences.

RLS: Critic sees own run only. Grader sees graded run only. Prompt optimizer sees TRAIN runs.

USEFUL FOR: Critic (write), grader (read), clustering (read).
- Critic: INSERT new findings during review
- Grader: read to match against ground truth
- Clustering: read unknowns (issues with no TP/FP match)'
    """)

    op.execute("""
        COMMENT ON TABLE reported_issue_occurrences IS
        'Locations where a reported issue occurs. Each occurrence has file path and line range.
Foreign key to reported_issues(agent_run_id, issue_id).

RLS: Same as reported_issues (scoped by agent_run_id).

USEFUL FOR: Critic (write), grader (read).
- Critic: INSERT occurrence locations when reporting issues
- Grader: read to verify location matches ground truth'
    """)

    op.execute("""
        COMMENT ON TABLE grading_decisions IS
        'Grader decisions matching reported issues to ground truth.
target_tp_id/target_fp_id = matched ground truth (NULL = no match).
credit = match quality (0-1). Trigger enforces SUM(credit) <= 1.0 per occurrence.

RLS: Grader sees own run only. Prompt optimizer sees TRAIN runs only.
Clustering agent sees decisions for its configured snapshot.

USEFUL FOR: Grader (write), prompt optimizer (read TRAIN only), clustering (read unknowns).
- Grader: INSERT decisions for each input issue
- Prompt optimizer: analyze which issues got credit vs not
- Clustering: read decisions with NULL targets (unknowns)'
    """)

    # Clustering-specific tables
    op.execute("""
        COMMENT ON TABLE unknown_clusters IS
        'Named clusters for grouping unknown issues (grading decisions with no TP/FP match).
Each cluster has a name and description. Created by clustering agent.

RLS: Clustering agent sees only own run. Scoped by agent_run_id in username.

USEFUL FOR: Clustering agent (write), analysis.
- Clustering: INSERT new clusters for discovered patterns
- Analysis: review what patterns were found'
    """)

    op.execute("""
        COMMENT ON TABLE unknown_assignments IS
        'Maps unknown grading decisions to clusters.
Each unknown can be assigned to a cluster, or mapped to an existing TP/FP.

RLS: Clustering agent sees only own run. Scoped by agent_run_id in username.

USEFUL FOR: Clustering agent (write).
- Clustering: INSERT assignments linking unknowns to clusters
- Mapping: link unknowns to existing TPs/FPs when appropriate'
    """)


def downgrade() -> None:
    # Remove comments (they don't cascade with DROP VIEW, but we reset them anyway)
    op.execute("COMMENT ON VIEW recall_by_run IS NULL")
    op.execute("COMMENT ON VIEW recall_by_definition_example IS NULL")
    op.execute("COMMENT ON VIEW recall_by_definition_split_kind IS NULL")
    op.execute("COMMENT ON VIEW recall_by_example IS NULL")
    op.execute("COMMENT ON VIEW occurrence_credits IS NULL")
    op.execute("COMMENT ON VIEW occurrence_statistics IS NULL")
    op.execute("COMMENT ON VIEW examples IS NULL")
    op.execute("COMMENT ON TABLE reported_issues IS NULL")
    op.execute("COMMENT ON TABLE reported_issue_occurrences IS NULL")
    op.execute("COMMENT ON TABLE grading_decisions IS NULL")
    op.execute("COMMENT ON TABLE unknown_clusters IS NULL")
    op.execute("COMMENT ON TABLE unknown_assignments IS NULL")

    # Drop the view
    op.execute("DROP VIEW IF EXISTS recall_by_example CASCADE")
