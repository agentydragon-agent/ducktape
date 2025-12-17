"""Add status to get_validation_run_aggregates function

Revision ID: 20251220000003
Revises: 20251217000003
Create Date: 2025-12-20 00:00:03.000000

Updates get_validation_run_aggregates() to return critic_run status so callers
can properly count successful vs failed runs instead of approximating.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000003"
down_revision: str | None = "20251217000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add status field to get_validation_run_aggregates() and fix critic_runs.status column type."""
    # Create enum type for critic run status (matches ORM type_annotation_map)
    op.execute("""
        CREATE TYPE critic_run_status_enum AS ENUM (
            'in_progress',
            'completed',
            'max_turns_exceeded',
            'context_length_exceeded',
            'reported_failure'
        )
    """)

    # Convert critic_runs.status from VARCHAR to enum type (fixes initial migration bug)
    # Views depend on this column, so drop/recreate them
    op.execute("DROP VIEW IF EXISTS critic_run_occurrence_stats CASCADE")

    # Step 1: Drop the default (text literal can't be cast to enum automatically)
    op.execute("ALTER TABLE critic_runs ALTER COLUMN status DROP DEFAULT")
    # Step 2: Convert column type
    op.execute("""
        ALTER TABLE critic_runs
        ALTER COLUMN status TYPE critic_run_status_enum
        USING status::critic_run_status_enum
    """)
    # Step 3: Re-add default with enum value
    op.execute("ALTER TABLE critic_runs ALTER COLUMN status SET DEFAULT 'in_progress'::critic_run_status_enum")

    # Recreate critic_run_occurrence_stats view reading from normalized grading_decisions table
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

            -- Average occurrences caught across graders (from normalized grading_decisions)
            AVG(
                CASE
                    WHEN cr.status = 'completed' AND gr.id IS NOT NULL THEN (
                        SELECT COALESCE(SUM(gd.credit), 0.0)
                        FROM grading_decisions gd
                        WHERE gd.grader_run_id = gr.id
                          AND gd.target_tp_id IS NOT NULL
                    )
                    ELSE NULL
                END
            ) as avg_occurrences_caught,

            -- Count catchable TP occurrences for this example (from first grader run)
            -- Multiple input issues may match the same TP occurrence, so count distinct
            COALESCE(
                (
                    SELECT COUNT(DISTINCT (gd.target_tp_id, gd.target_tp_occurrence_id))::integer
                    FROM grading_decisions gd
                    WHERE gd.grader_run_id = (
                        SELECT id FROM grader_runs WHERE critic_run_id = cr.id LIMIT 1
                    )
                    AND gd.target_tp_id IS NOT NULL
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

    # Recreate dependent views (dropped by CASCADE)
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
            SUM(CASE WHEN status = 'reported_failure' THEN 1 ELSE 0 END)::integer as n_reported_failure,

            -- Distinct examples vs total runs (can have multiple runs per example)
            COUNT(DISTINCT (snapshot_slug, scope_hash))::integer as n_examples,
            COUNT(*)::integer as n_runs,

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

            -- Computed recall (with safe division)
            CASE
                WHEN AVG(n_catchable_occurrences) > 0
                THEN AVG(COALESCE(avg_occurrences_caught, 0.0)) / AVG(n_catchable_occurrences)
                ELSE NULL
            END as recall,

            -- Confidence bounds (UCB/LCB) using standard error
            CASE
                WHEN AVG(n_catchable_occurrences) > 0 AND COUNT(*) > 1
                THEN AVG(COALESCE(avg_occurrences_caught, 0.0)) / AVG(n_catchable_occurrences)
                     + STDDEV_SAMP(COALESCE(avg_occurrences_caught, 0.0) / NULLIF(n_catchable_occurrences, 0)) / SQRT(COUNT(*))
                ELSE NULL
            END as ucb,
            CASE
                WHEN AVG(n_catchable_occurrences) > 0 AND COUNT(*) > 1
                THEN AVG(COALESCE(avg_occurrences_caught, 0.0)) / AVG(n_catchable_occurrences)
                     - STDDEV_SAMP(COALESCE(avg_occurrences_caught, 0.0) / NULLIF(n_catchable_occurrences, 0)) / SQRT(COUNT(*))
                ELSE NULL
            END as lcb,

            -- Grader metadata
            AVG(n_grader_runs) as avg_grader_runs_per_critic,
            SUM(n_grader_runs)::integer as total_grader_runs

        FROM critic_run_occurrence_stats
        GROUP BY prompt_sha256, split, critic_model, scope_kind
    """)

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
            SUM(CASE WHEN status = 'reported_failure' THEN 1 ELSE 0 END)::integer as n_reported_failure,

            -- Total runs for this (example, critic_model) combination
            COUNT(*)::integer as n_runs,

            -- Occurrence counts (not percentages!)
            AVG(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as avg_occurrences_caught_among_successful,
            VAR_SAMP(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as occurrences_variance_among_successful,
            AVG(COALESCE(avg_occurrences_caught, 0.0)) as avg_occurrences_caught_overall,

            -- Catchable occurrences (for dataset-level recall)
            AVG(n_catchable_occurrences) as avg_catchable_occurrences,
            SUM(n_catchable_occurrences)::integer as total_catchable_occurrences,

            -- Computed recall (with safe division)
            CASE
                WHEN AVG(n_catchable_occurrences) > 0
                THEN AVG(COALESCE(avg_occurrences_caught, 0.0)) / AVG(n_catchable_occurrences)
                ELSE NULL
            END as recall,

            -- Grader metadata
            AVG(n_grader_runs) as avg_grader_runs_per_critic,
            SUM(n_grader_runs)::integer as total_grader_runs

        FROM critic_run_occurrence_stats
        GROUP BY snapshot_slug, scope_hash, split, critic_model
    """)

    # Recreate pareto_frontier_by_example view (depends on critic_run_occurrence_stats)
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

    # Drop old function
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    # Recreate with status field
    op.execute("""
        CREATE FUNCTION get_validation_run_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            prompt_sha256 text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status critic_run_status_enum,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.prompt_sha256,
                oc.critic_model,
                oc.grader_model,
                oc.critic_run_id,
                oc.grader_run_id,
                cr.status,
                oc.tp_id,
                oc.occurrence_id,
                AVG(oc.found_credit) as avg_credit
            FROM occurrence_credits oc
            JOIN snapshots s ON oc.snapshot_slug = s.slug
            JOIN critic_runs cr ON oc.critic_run_id = cr.id
            WHERE s.split = 'valid'::split_enum
              AND oc.scope_kind = 'entire_snapshot'
            GROUP BY oc.snapshot_slug, oc.prompt_sha256, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, cr.status, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            prompt_sha256,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            status,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id, status
          ORDER BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION get_validation_run_aggregates() IS
        'Black-box validation metrics for whole-repo mode.
        Returns per-run recall for VALID split, entire_snapshot scope_kind only.
        Includes critic_run status for proper outcome counting.
        Used by prompt optimizer in whole-repo validation mode.'
    """)


def downgrade() -> None:
    """Remove status field from get_validation_run_aggregates() and revert critic_runs.status to VARCHAR."""
    # Drop modified function
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    # Recreate original without status field
    op.execute("""
        CREATE FUNCTION get_validation_run_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            prompt_sha256 text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.prompt_sha256,
                oc.critic_model,
                oc.grader_model,
                oc.critic_run_id,
                oc.grader_run_id,
                oc.tp_id,
                oc.occurrence_id,
                AVG(oc.found_credit) as avg_credit
            FROM occurrence_credits oc
            JOIN snapshots s ON oc.snapshot_slug = s.slug
            WHERE s.split = 'valid'::split_enum
              AND oc.scope_kind = 'entire_snapshot'
            GROUP BY oc.snapshot_slug, oc.prompt_sha256, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            prompt_sha256,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id
          ORDER BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION get_validation_run_aggregates() IS
        'Black-box validation metrics for whole-repo mode.
        Returns per-run recall for VALID split, entire_snapshot scope_kind only.
        Used by prompt optimizer in whole-repo validation mode.'
    """)

    # Drop the normalized-tables-based view
    op.execute("DROP VIEW IF EXISTS critic_run_occurrence_stats CASCADE")

    # Revert critic_runs.status to VARCHAR (original type)
    # Step 1: Drop the enum-typed default
    op.execute("ALTER TABLE critic_runs ALTER COLUMN status DROP DEFAULT")
    # Step 2: Convert column type back to VARCHAR
    op.execute("""
        ALTER TABLE critic_runs
        ALTER COLUMN status TYPE varchar
        USING status::text
    """)
    # Step 3: Re-add default with text value
    op.execute("ALTER TABLE critic_runs ALTER COLUMN status SET DEFAULT 'in_progress'")

    # Recreate original JSONB-based view (from migration 20251217000003)
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
            AVG(
                CASE
                    WHEN cr.status = 'completed' AND gr.id IS NOT NULL THEN (
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
            (
                SELECT COUNT(*)
                FROM true_positives tp
                CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) AS occ
                WHERE tp.snapshot_slug = cr.snapshot_slug
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(occ->'expect_caught_from') AS trigger_set_json
                      CROSS JOIN LATERAL (
                          SELECT jsonb_array_elements_text(trigger_set_json) AS file
                      ) trigger_files
                      GROUP BY trigger_set_json
                      HAVING bool_and(
                          trigger_files.file = ANY(
                              SELECT jsonb_array_elements_text(e.scope->'files')
                          )
                      )
                  )
            ) as n_catchable_occurrences
        FROM critic_runs cr
        JOIN snapshots s ON cr.snapshot_slug = s.slug
        JOIN examples e ON cr.snapshot_slug = e.snapshot_slug AND cr.scope_hash = e.scope_hash
        LEFT JOIN grader_runs gr ON gr.critic_run_id = cr.id
        GROUP BY cr.id, cr.prompt_sha256, cr.snapshot_slug, cr.scope_hash, s.split,
                 cr.model, cr.status, e.scope
    """)

    # Drop the enum type
    op.execute("DROP TYPE IF EXISTS critic_run_status_enum CASCADE")
