"""Aggregate over graders with occurrence-based weighting

Revision ID: 20251217000001
Revises: 20251220000002
Create Date: 2025-12-17 00:00:01.000000

Changes aggregated_recall_by_prompt and aggregated_recall_by_example to:
1. Remove grader_model from GROUP BY (aggregate over all graders)
2. Compute raw occurrence counts instead of percentages (enables occurrence-based weighting)
3. Add n_catchable_occurrences tracking for dataset-level recall computation
4. Add explicit failure count columns (n_successful, n_max_turns_exceeded, n_context_length_exceeded)
5. Split metrics: avg_occurrences_caught_among_successful vs avg_occurrences_caught_overall
6. Add variance metrics for successful runs
7. Add grader metadata (avg_grader_runs_per_critic, total_grader_runs)

Rationale:
- Failed critic runs (max_turns/context_length) never get graded (grader_model = NULL)
- Grouping by grader_model splits failed runs into separate rows
- Users expect "one row per (prompt, split, critic_model)" for simple queries
- Occurrence-based weighting: examples with more occurrences contribute proportionally more
- Dataset-level recall: SUM(avg_occurrences_caught) / SUM(n_catchable_occurrences)
- Keep occurrence_run_credits with grader_model for detailed per-grader analysis
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251217000001"
down_revision: str | None = "20251220000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop existing views (will be recreated with new schema)
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")

    # Create intermediate view: per-critic-run occurrence statistics
    # This eliminates duplication of n_catchable_occurrences computation
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

        GROUP BY cr.id, cr.prompt_sha256, cr.snapshot_slug, cr.scope_hash, s.split, cr.model, cr.status
    """)

    op.execute("""
        COMMENT ON VIEW critic_run_occurrence_stats IS
        'Per-critic-run occurrence statistics aggregated over all graders.

        Intermediate view that computes:
        - avg_occurrences_caught: Average raw occurrence count across graders for this run
        - n_catchable_occurrences: Total occurrences that could be caught (computed once)
        - n_grader_runs: How many graders ran on this critic run

        This eliminates duplication - both aggregated_recall_by_prompt and
        aggregated_recall_by_example SELECT from this view.

        Failed critic runs (max_turns/context_length) have avg_occurrences_caught = NULL.'
    """)

    # Recreate aggregated_recall_by_prompt using the intermediate view
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

    # Recreate aggregated_recall_by_example using the intermediate view
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

            -- Overall (failed = 0.0)
            AVG(COALESCE(avg_occurrences_caught, 0.0)) as avg_occurrences_caught_overall,

            -- Catchable occurrences
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

        Same semantics as aggregated_recall_by_prompt but grouped by
        (snapshot_slug, scope_hash) instead of prompt_sha256.

        OCCURRENCE-BASED WEIGHTING: This view computes raw occurrence counts (not percentages).
        See aggregated_recall_by_prompt comment for detailed explanation and column descriptions.'
    """)


def downgrade() -> None:
    # Drop new views (including intermediate view)
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS critic_run_occurrence_stats CASCADE")

    # Recreate old views with grader_model in GROUP BY
    # (This is the schema from 20251220000002)
    op.execute("""
        CREATE VIEW aggregated_recall_by_prompt AS
        SELECT
            prompt_sha256,
            split,
            critic_model,
            grader_model,
            COUNT(*) as n_examples,
            SUM(total_credit) as total_credit,
            SUM(n_occurrences) as n_occurrences,
            CASE
                WHEN SUM(n_occurrences) > 0
                THEN SUM(total_credit) / SUM(n_occurrences)
                ELSE 0.0
            END as recall,
            AVG(recall) - STDDEV(recall) / SQRT(COUNT(*)) as lcb,
            AVG(recall) + STDDEV(recall) / SQRT(COUNT(*)) as ucb
        FROM occurrence_run_credits
        GROUP BY prompt_sha256, split, critic_model, grader_model
    """)

    op.execute("""
        CREATE VIEW aggregated_recall_by_example AS
        SELECT
            split,
            snapshot_slug,
            scope_hash,
            critic_model,
            grader_model,
            SUM(total_credit) as total_credit,
            SUM(n_occurrences) as n_occurrences,
            CASE
                WHEN SUM(n_occurrences) > 0
                THEN SUM(total_credit) / SUM(n_occurrences)
                ELSE 0.0
            END as recall,
            COUNT(DISTINCT critic_run_id) as n_critic_runs
        FROM occurrence_run_credits
        GROUP BY split, snapshot_slug, scope_hash, critic_model, grader_model
    """)
