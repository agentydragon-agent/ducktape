"""Add scope_kind to aggregated_recall_by_prompt

Revision ID: 20251217000003
Revises: 20251217000002
Create Date: 2025-12-17 00:00:03.000000

Updates aggregated_recall_by_prompt view to include scope_kind in GROUP BY.
This allows filtering/grouping stats by scope type (entire_snapshot vs explicit_files).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251217000003"
down_revision: str | None = "20251217000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # First, drop the views that depend on critic_run_occurrence_stats
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")

    # Drop and recreate critic_run_occurrence_stats with scope_kind
    op.execute("DROP VIEW IF EXISTS critic_run_occurrence_stats CASCADE")

    op.execute("""
        CREATE VIEW critic_run_occurrence_stats AS
        SELECT
            cr.id as critic_run_id,
            cr.prompt_sha256,
            cr.snapshot_slug,
            cr.scope_hash,
            s.split,
            cr.model as critic_model,
            cr.status,
            e.scope->>'kind' AS scope_kind,

            -- Average occurrences caught across graders for this critic run
            -- For failed runs (status != 'completed'), this will be NULL
            AVG(
                CASE
                    WHEN cr.status = 'completed' AND gr.id IS NOT NULL THEN (
                        -- Sum of found_credit (NOT divided by count)
                        COALESCE(
                            (
                                SELECT SUM((occ->>'found_credit')::float)
                                FROM jsonb_array_elements(
                                    (gr.output->'occurrence_results')
                                ) occ
                            ),
                            0.0
                        )
                    )
                    ELSE NULL
                END
            ) as avg_occurrences_caught,

            -- How many occurrences could be caught for this example
            -- Computed once here instead of in each aggregate view
            COALESCE(
                (
                    SELECT COUNT(*)::integer
                    FROM jsonb_array_elements(
                        (SELECT gr2.output->'occurrence_results'
                         FROM grader_runs gr2
                         WHERE gr2.critic_run_id = cr.id
                         LIMIT 1)
                    ) occ
                ),
                0
            ) as n_catchable_occurrences,

            -- Count how many graders ran on this critic run
            COUNT(gr.id) as n_grader_runs

        FROM critic_runs cr
        JOIN examples e ON (cr.snapshot_slug, cr.scope_hash) = (e.snapshot_slug, e.scope_hash)
        JOIN snapshots s ON e.snapshot_slug = s.slug
        LEFT JOIN grader_runs gr ON gr.critic_run_id = cr.id

        GROUP BY cr.id, cr.prompt_sha256, cr.snapshot_slug, cr.scope_hash, s.split, cr.model, cr.status, e.scope
    """)

    op.execute("""
        COMMENT ON VIEW critic_run_occurrence_stats IS
        'Per-critic-run occurrence statistics aggregated over all graders.
        Now includes scope_kind for filtering by scope type.

        Intermediate view that computes:
        - avg_occurrences_caught: Average raw occurrence count across graders for this run
        - n_catchable_occurrences: Total occurrences that could be caught (computed once)
        - n_grader_runs: How many graders ran on this critic run
        - scope_kind: Scope type (entire_snapshot or explicit_files)

        This eliminates duplication - both aggregated_recall_by_prompt and
        aggregated_recall_by_example SELECT from this view.

        Failed critic runs (max_turns/context_length) have avg_occurrences_caught = NULL.'
    """)

    # Recreate aggregated_recall_by_prompt with scope_kind in GROUP BY
    op.execute("""
        CREATE VIEW aggregated_recall_by_prompt AS
        SELECT
            prompt_sha256,
            split,
            critic_model,
            scope_kind,

            -- Count by outcome
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)::integer as n_successful,
            SUM(CASE WHEN status = 'max_turns_exceeded' THEN 1 ELSE 0 END)::integer as n_max_turns_exceeded,
            SUM(CASE WHEN status = 'context_length_exceeded' THEN 1 ELSE 0 END)::integer as n_context_length_exceeded,

            -- Occurrence counts (not percentages!)
            AVG(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as avg_occurrences_caught_among_successful,
            VAR_SAMP(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as occurrences_variance_among_successful,

            -- Overall (failed = 0.0)
            AVG(COALESCE(avg_occurrences_caught, 0.0)) as avg_occurrences_caught_overall,

            -- How many occurrences COULD be caught (for dataset-level recall computation)
            AVG(n_catchable_occurrences) as avg_catchable_occurrences,
            SUM(n_catchable_occurrences)::integer as total_catchable_occurrences,

            -- Grader metadata
            AVG(n_grader_runs) as avg_grader_runs_per_critic,
            SUM(n_grader_runs)::integer as total_grader_runs

        FROM critic_run_occurrence_stats
        GROUP BY prompt_sha256, split, critic_model, scope_kind
    """)

    op.execute("""
        COMMENT ON VIEW aggregated_recall_by_prompt IS
        'Per-prompt aggregate metrics with occurrence-based weighting, averaged over all grader models.
        Now includes scope_kind dimension for filtering by scope type.

        OCCURRENCE-BASED WEIGHTING: This view computes raw occurrence counts (not percentages).
        When computing dataset-level recall, sum avg_occurrences_caught and sum total_catchable_occurrences
        across rows, then divide: SUM(avg_occurrences_caught) / SUM(total_catchable_occurrences).
        This naturally weights examples by their occurrence count (20 occurrences = 20x weight of 1 occurrence).

        When a critic run is graded multiple times (by different graders), we first
        average its occurrence counts, then aggregate across runs.

        Failed runs (max_turns/context_length) count as zero occurrences in avg_occurrences_caught_overall
        but are excluded from avg_occurrences_caught_among_successful.

        Columns:
        - prompt_sha256: Prompt identifier
        - split: train/valid/test
        - critic_model: Model used for critic
        - scope_kind: entire_snapshot or explicit_files
        - n_successful: Critic runs that completed successfully
        - n_max_turns_exceeded: Critic runs that hit turn limit
        - n_context_length_exceeded: Critic runs that hit context limit
        - avg_occurrences_caught_among_successful: Avg occurrences caught (successful runs only, raw count)
        - occurrences_variance_among_successful: Variance in occurrences caught (successful runs, NULL if < 2)
        - avg_occurrences_caught_overall: Avg occurrences caught (includes failures as 0.0, raw count)
        - avg_catchable_occurrences: Avg number of occurrences that could be caught
        - total_catchable_occurrences: Total occurrences that could be caught (for dataset-level recall)
        - avg_grader_runs_per_critic: Average number of graders per critic run
        - total_grader_runs: Total number of grader runs

        Use occurrence_run_credits for per-grader-model analysis.'
    """)

    # Recreate aggregated_recall_by_example (unchanged, but needs to be recreated because it depends on critic_run_occurrence_stats)
    op.execute("""
        CREATE VIEW aggregated_recall_by_example AS
        SELECT
            snapshot_slug,
            scope_hash,
            split,
            critic_model,

            -- Count by outcome
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)::integer as n_successful,
            SUM(CASE WHEN status = 'max_turns_exceeded' THEN 1 ELSE 0 END)::integer as n_max_turns_exceeded,
            SUM(CASE WHEN status = 'context_length_exceeded' THEN 1 ELSE 0 END)::integer as n_context_length_exceeded,

            -- Occurrence counts (not percentages!)
            AVG(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as avg_occurrences_caught_among_successful,
            VAR_SAMP(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as occurrences_variance_among_successful,
            AVG(COALESCE(avg_occurrences_caught, 0.0)) as avg_occurrences_caught_overall,

            -- Catchable occurrences (for dataset-level recall)
            AVG(n_catchable_occurrences) as avg_catchable_occurrences,
            SUM(n_catchable_occurrences)::integer as total_catchable_occurrences,

            -- Grader metadata
            AVG(n_grader_runs) as avg_grader_runs_per_critic,
            SUM(n_grader_runs)::integer as total_grader_runs

        FROM critic_run_occurrence_stats
        GROUP BY snapshot_slug, scope_hash, split, critic_model
    """)

    op.execute("""
        COMMENT ON VIEW aggregated_recall_by_example IS
        'Per-example aggregate metrics with occurrence-based weighting, averaged over all grader models.

        Uses occurrence-based weighting identical to aggregated_recall_by_prompt.
        Grouped by example (snapshot_slug, scope_hash) instead of prompt.'
    """)

    # Recreate pareto_frontier_by_example (dropped by CASCADE when critic_run_occurrence_stats was dropped)
    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH per_run_recalls AS (
            -- Compute per-run recall using occurrence-based weighting
            -- Uses critic_run_occurrence_stats which already aggregates over graders
            SELECT
                cros.split,
                cros.snapshot_slug,
                cros.scope_hash,
                cros.scope_kind,
                cros.prompt_sha256,
                cros.critic_run_id,
                cros.critic_model,
                -- Occurrence-based recall: occurrences caught / catchable occurrences
                -- Failed runs have NULL avg_occurrences_caught, treated as 0.0 for recall
                CASE
                    WHEN cros.n_catchable_occurrences > 0
                    THEN COALESCE(cros.avg_occurrences_caught, 0.0) / cros.n_catchable_occurrences
                    ELSE 0.0
                END AS recall
            FROM critic_run_occurrence_stats cros
        ),
        avg_recall_per_prompt_example AS (
            -- Average recall across runs for each (snapshot, scope_hash, prompt)
            SELECT
                split,
                snapshot_slug,
                scope_hash,
                scope_kind,
                prompt_sha256,
                critic_model,
                AVG(recall) AS avg_recall,
                COUNT(DISTINCT critic_run_id) AS n_runs
            FROM per_run_recalls
            GROUP BY split, snapshot_slug, scope_hash, scope_kind, prompt_sha256, critic_model
        ),
        best_scores AS (
            -- Find best recall per example
            SELECT
                split,
                snapshot_slug,
                scope_hash,
                scope_kind,
                critic_model,
                MAX(avg_recall) AS best_recall
            FROM avg_recall_per_prompt_example
            GROUP BY split, snapshot_slug, scope_hash, scope_kind, critic_model
        )
        SELECT
            bs.split,
            bs.snapshot_slug,
            bs.scope_hash,
            bs.scope_kind,
            bs.critic_model,
            bs.best_recall,
            array_agg(arppe.prompt_sha256 ORDER BY arppe.prompt_sha256) AS winning_prompt_shas,
            array_agg(arppe.n_runs ORDER BY arppe.prompt_sha256) AS winning_prompt_n_runs
        FROM best_scores bs
        JOIN avg_recall_per_prompt_example arppe ON
            bs.split = arppe.split AND
            bs.snapshot_slug = arppe.snapshot_slug AND
            bs.scope_hash = arppe.scope_hash AND
            bs.scope_kind = arppe.scope_kind AND
            bs.critic_model = arppe.critic_model AND
            bs.best_recall = arppe.avg_recall
        GROUP BY bs.split, bs.snapshot_slug, bs.scope_hash, bs.scope_kind, bs.critic_model, bs.best_recall
    """)

    op.execute("""
        COMMENT ON VIEW pareto_frontier_by_example IS
        'Pareto frontier: best recall achieved on each example and which prompt SHAs achieved it.

        Uses occurrence-based weighting: recall = occurrences_caught / catchable_occurrences.
        This naturally weights examples by their issue density (20 occurrences = 20x weight of 1 occurrence).

        For each (split, snapshot_slug, scope_hash, critic_model), shows the best average recall
        across all prompts and lists all prompt SHAs (SHA256 hashes) that achieved this best score.

        Built on critic_run_occurrence_stats, which already aggregates over grader models.
        Failed critic runs (max_turns/context_length) count as 0.0 recall.

        Use cases:
        - Prompt optimization: Which prompts excel on specific examples?
        - Ensemble analysis: Combine best prompts for different patterns
        - Training diagnostics: Where do all prompts struggle?'
    """)


def downgrade() -> None:
    # Drop new view
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")

    # Recreate old view without scope_kind
    op.execute("""
        CREATE VIEW aggregated_recall_by_prompt AS
        SELECT
            prompt_sha256,
            split,
            critic_model,

            -- Count by outcome
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)::integer as n_successful,
            SUM(CASE WHEN status = 'max_turns_exceeded' THEN 1 ELSE 0 END)::integer as n_max_turns_exceeded,
            SUM(CASE WHEN status = 'context_length_exceeded' THEN 1 ELSE 0 END)::integer as n_context_length_exceeded,

            -- Occurrence counts (not percentages!)
            AVG(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as avg_occurrences_caught_among_successful,
            VAR_SAMP(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as occurrences_variance_among_successful,

            -- Overall (failed = 0.0)
            AVG(COALESCE(avg_occurrences_caught, 0.0)) as avg_occurrences_caught_overall,

            -- How many occurrences COULD be caught (for dataset-level recall computation)
            AVG(n_catchable_occurrences) as avg_catchable_occurrences,
            SUM(n_catchable_occurrences)::integer as total_catchable_occurrences,

            -- Grader metadata
            AVG(n_grader_runs) as avg_grader_runs_per_critic,
            SUM(n_grader_runs)::integer as total_grader_runs

        FROM critic_run_occurrence_stats
        GROUP BY prompt_sha256, split, critic_model
    """)

    op.execute("""
        COMMENT ON VIEW aggregated_recall_by_prompt IS
        'Per-prompt aggregate metrics with occurrence-based weighting, averaged over all grader models.

        OCCURRENCE-BASED WEIGHTING: This view computes raw occurrence counts (not percentages).
        When computing dataset-level recall, sum avg_occurrences_caught and sum total_catchable_occurrences
        across rows, then divide: SUM(avg_occurrences_caught) / SUM(total_catchable_occurrences).
        This naturally weights examples by their occurrence count (20 occurrences = 20x weight of 1 occurrence).

        When a critic run is graded multiple times (by different graders), we first
        average its occurrence counts, then aggregate across runs.

        Failed runs (max_turns/context_length) count as zero occurrences in avg_occurrences_caught_overall
        but are excluded from avg_occurrences_caught_among_successful.

        Columns:
        - n_successful: Critic runs that completed successfully
        - n_max_turns_exceeded: Critic runs that hit turn limit
        - n_context_length_exceeded: Critic runs that hit context limit
        - avg_occurrences_caught_among_successful: Avg occurrences caught (successful runs only, raw count)
        - occurrences_variance_among_successful: Variance in occurrences caught (successful runs, NULL if < 2)
        - avg_occurrences_caught_overall: Avg occurrences caught (includes failures as 0.0, raw count)
        - avg_catchable_occurrences: Avg number of occurrences that could be caught
        - total_catchable_occurrences: Total occurrences that could be caught (for dataset-level recall)
        - avg_grader_runs_per_critic: Average number of graders per critic run
        - total_grader_runs: Total number of grader runs

        Use occurrence_run_credits for per-grader-model analysis.'
    """)
