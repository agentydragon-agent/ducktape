"""Simplify grading views: drop grader_run_id as aggregation dimension.

New grading model: grader_run_id is provenance (which container created an edge),
not an aggregation dimension. A TP occurrence on a critique gets total credit <= 1.0
(enforced by check_edge_credit_sum). No "multiple independent re-gradings".

Changes:
- Rename occurrence_credits -> tp_occurrence_credits (SUMs credit per critique+occurrence)
- DROP occurrence_run_credits (intermediate grader_run grouping no longer needed)
- Simplify occurrence_statistics (aggregate across critic runs, not grader runs)
- Simplify recall_by_run (scalar total_credit instead of StatsWithCI across graders)
- Simplify get_validation_full_snapshot_aggregates (remove grader_run_id/grader_model)
- Recreate all downstream views

Revision ID: 20260129000000
Revises: 20251228000000
Create Date: 2026-01-29
"""

from alembic import op

revision = "20260129000000"
down_revision = "20251228000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. DROP all affected views and function in reverse dependency order
    # =========================================================================
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example")
    op.execute("DROP VIEW IF EXISTS validation_recall_by_definition")
    op.execute("DROP VIEW IF EXISTS recall_by_example")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_split_kind")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_example")
    op.execute("DROP VIEW IF EXISTS recall_by_run")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits")
    op.execute("DROP VIEW IF EXISTS occurrence_credits")
    op.execute("DROP FUNCTION IF EXISTS get_validation_full_snapshot_aggregates()")

    # =========================================================================
    # 2. Create tp_occurrence_credits (renamed from occurrence_credits)
    # =========================================================================
    op.execute("""
        CREATE VIEW tp_occurrence_credits AS
        -- Graded occurrences: SUM credit per (critique_run, tp, occurrence)
        SELECT
            ge.snapshot_slug,
            s.split,
            ex.example_kind,
            ex.files_hash,
            ge.tp_id,
            ge.tp_occurrence_id AS occurrence_id,
            ge.critique_run_id AS critic_run_id,
            cr.image_digest AS critic_image_digest,
            cr.model AS critic_model,
            SUM(ge.credit) AS found_credit
        FROM grading_edges ge
        JOIN agent_runs cr ON cr.agent_run_id = ge.critique_run_id
        JOIN snapshots s ON ge.snapshot_slug = s.slug
        JOIN examples ex ON (
            ge.snapshot_slug = ex.snapshot_slug
            AND (cr.type_config->'example'->>'kind')::example_kind_enum = ex.example_kind
            AND COALESCE((cr.type_config->'example'->>'files_hash'), '') = COALESCE(ex.files_hash, '')
        )
        WHERE ge.tp_id IS NOT NULL
          AND (cr.type_config->>'agent_type') = 'critic'
        GROUP BY ge.snapshot_slug, s.split, ex.example_kind, ex.files_hash,
                 ge.tp_id, ge.tp_occurrence_id,
                 ge.critique_run_id, cr.image_digest, cr.model

        UNION ALL

        -- Failed critics: zero-credit rows for all occurrences in expected recall scope
        SELECT
            (cr.type_config->'example'->>'snapshot_slug') AS snapshot_slug,
            s.split,
            ex.example_kind,
            ex.files_hash,
            tpo.tp_id,
            tpo.occurrence_id,
            cr.agent_run_id AS critic_run_id,
            cr.image_digest AS critic_image_digest,
            cr.model AS critic_model,
            0.0 AS found_credit
        FROM agent_runs cr
        JOIN snapshots s ON (cr.type_config->'example'->>'snapshot_slug') = s.slug
        JOIN examples ex ON (
            (cr.type_config->'example'->>'snapshot_slug') = ex.snapshot_slug
            AND (cr.type_config->'example'->>'kind')::example_kind_enum = ex.example_kind
            AND COALESCE((cr.type_config->'example'->>'files_hash'), '') = COALESCE(ex.files_hash, '')
        )
        CROSS JOIN true_positive_occurrences tpo
        WHERE (cr.type_config->>'agent_type') = 'critic'
          AND cr.status = 'timed_out'::agent_run_status_enum
          AND (cr.type_config->'example'->>'snapshot_slug') = tpo.snapshot_slug
          AND is_tp_in_expected_recall_scope(tpo.snapshot_slug, tpo.tp_id, ex.example_kind, ex.files_hash)
    """)

    op.execute("""
        COMMENT ON VIEW tp_occurrence_credits IS
        'Per-(critique_run, tp, occurrence) credit. SUM of all grading edge credits.
Each row = one TP occurrence on one critic run with its total found_credit (0-1).
grader_run_id is not exposed — it is provenance, not an aggregation dimension.
Failed critics produce zero-credit rows for all occurrences in expected recall scope.

USEFUL FOR: Prompt optimizer (TRAIN split via RLS), improvement agent.'
    """)

    # =========================================================================
    # 3. occurrence_statistics — aggregate across critic runs, not grader runs
    # =========================================================================
    op.execute("""
        CREATE VIEW occurrence_statistics AS
        SELECT
            snapshot_slug,
            split,
            example_kind,
            files_hash,
            tp_id,
            occurrence_id,
            critic_image_digest,
            critic_model,
            compute_stats_with_ci(array_agg(found_credit)) AS credit_stats
        FROM tp_occurrence_credits
        GROUP BY snapshot_slug, split, example_kind, files_hash, tp_id, occurrence_id,
            critic_image_digest, critic_model
    """)

    op.execute("""
        COMMENT ON VIEW occurrence_statistics IS
        'Aggregate statistics per occurrence across critic runs.
credit_stats.n = number of critic runs, credit_stats.mean = avg credit across runs.

USEFUL FOR: Prompt optimizer, improvement agent.
- Find consistently-missed occurrences (low credit_stats.mean across runs)
- Identify occurrence patterns that need prompt improvements'
    """)

    # =========================================================================
    # 4. recall_by_run — scalar total_credit per critic run
    # =========================================================================
    op.execute("""
        CREATE VIEW recall_by_run AS
        WITH per_run AS (
            SELECT
                cr.type_config->'example'->>'snapshot_slug' AS snapshot_slug,
                e.example_kind,
                e.files_hash,
                s.split,
                e.recall_denominator,
                cr.agent_run_id AS critic_run_id,
                cr.image_digest AS critic_image_digest,
                cr.model AS critic_model,
                cr.status AS critic_status,
                CASE
                    WHEN cr.status = 'completed' THEN
                        COALESCE((
                            SELECT SUM(toc.found_credit)
                            FROM tp_occurrence_credits toc
                            WHERE toc.critic_run_id = cr.agent_run_id
                        ), 0.0)
                    ELSE 0.0
                END AS total_credit
            FROM agent_runs cr
            JOIN examples e ON (
                cr.type_config->'example'->>'snapshot_slug' = e.snapshot_slug
                AND (cr.type_config->'example'->>'kind')::example_kind_enum = e.example_kind
                AND COALESCE((cr.type_config->'example'->>'files_hash'), '') = COALESCE(e.files_hash, '')
            )
            JOIN snapshots s ON cr.type_config->'example'->>'snapshot_slug' = s.slug
            WHERE (cr.type_config->>'agent_type') = 'critic'
              AND cr.status != 'in_progress'
        )
        SELECT
            snapshot_slug, example_kind, files_hash, split, recall_denominator,
            critic_run_id, critic_image_digest, critic_model, critic_status,
            total_credit,
            CASE WHEN recall_denominator > 0
                THEN total_credit / recall_denominator
                ELSE 0.0
            END AS recall
        FROM per_run
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_run IS
        'Per-critic-run recall. Scalar total_credit (sum of all TP occurrence credits)
and scalar recall (total_credit / recall_denominator). Base view for all recall aggregates.'
    """)

    # =========================================================================
    # 5. recall_by_definition_example — aggregate scalar total_credit across runs
    # =========================================================================
    op.execute("""
        CREATE VIEW recall_by_definition_example AS
        WITH raw_stats AS (
            SELECT
                rbr.critic_image_digest,
                rbr.critic_model,
                rbr.snapshot_slug,
                rbr.example_kind,
                rbr.files_hash,
                rbr.split,
                MAX(rbr.recall_denominator)::integer AS recall_denominator,
                COUNT(*)::integer AS n_runs,
                agg_status_counts(array_agg(rbr.critic_status)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    rbr.total_credit
                )) AS credit_stats
            FROM recall_by_run rbr
            GROUP BY rbr.critic_image_digest, rbr.critic_model,
                     rbr.snapshot_slug, rbr.example_kind, rbr.files_hash, rbr.split
        )
        SELECT
            critic_image_digest, critic_model,
            snapshot_slug, example_kind, files_hash, split,
            recall_denominator, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, recall_denominator) AS recall_stats
        FROM raw_stats
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_example IS
        'Recall aggregated by (definition, example). Stats computed across critic runs.'
    """)

    # =========================================================================
    # 6. recall_by_definition_split_kind — unchanged structure
    # =========================================================================
    op.execute("""
        CREATE VIEW recall_by_definition_split_kind AS
        WITH
        example_counts AS (
            SELECT
                split, example_kind, critic_image_digest, critic_model,
                COUNT(*)::integer AS n_examples,
                SUM(recall_denominator)::integer AS recall_denominator
            FROM (
                SELECT DISTINCT
                    split, example_kind, files_hash, recall_denominator,
                    critic_image_digest, critic_model
                FROM recall_by_definition_example
            ) per_example
            GROUP BY split, example_kind, critic_image_digest, critic_model
        ),
        run_stats AS (
            SELECT
                split, example_kind, critic_image_digest, critic_model,
                COUNT(*)::integer AS n_runs,
                agg_status_counts(array_agg(status_counts)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((credit_stats).mean, 0.0)
                )) AS credit_stats,
                COUNT(*) FILTER (WHERE COALESCE((credit_stats).mean, 0.0) = 0.0)::integer AS zero_count
            FROM recall_by_definition_example
            GROUP BY split, example_kind, critic_image_digest, critic_model
        )
        SELECT
            rs.split, rs.example_kind, rs.critic_image_digest, rs.critic_model,
            ec.n_examples, rs.n_runs, ec.recall_denominator,
            rs.status_counts, rs.credit_stats,
            scale_stats(rs.credit_stats, ec.recall_denominator) AS recall_stats,
            rs.zero_count
        FROM run_stats rs
        JOIN example_counts ec USING (split, example_kind, critic_image_digest, critic_model)
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_split_kind IS
        'Recall aggregated by (definition, split, example_kind).'
    """)

    # =========================================================================
    # 7. recall_by_example — unchanged structure
    # =========================================================================
    op.execute("""
        CREATE VIEW recall_by_example AS
        WITH raw_stats AS (
            SELECT
                rbde.snapshot_slug,
                rbde.example_kind,
                rbde.files_hash,
                rbde.split,
                MAX(rbde.recall_denominator)::integer AS recall_denominator,
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
            recall_denominator, critic_model, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, recall_denominator) AS recall_stats
        FROM raw_stats
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_example IS
        'Recall aggregated by example (across all definitions).'
    """)

    # =========================================================================
    # 8. pareto_frontier_by_example — unchanged structure
    # =========================================================================
    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH best_scores AS (
            SELECT
                snapshot_slug,
                example_kind,
                files_hash,
                split,
                MAX(recall_denominator) AS recall_denominator,
                critic_model,
                MAX(COALESCE((credit_stats).mean, 0.0)) AS best_mean_credit
            FROM recall_by_definition_example
            GROUP BY snapshot_slug, example_kind, files_hash, split, critic_model
        ),
        ranked AS (
            SELECT
                rbde.*,
                (rbde.credit_stats).mean AS mean_credit,
                bs.best_mean_credit
            FROM recall_by_definition_example rbde
            JOIN best_scores bs USING (snapshot_slug, example_kind, files_hash, split, critic_model)
            WHERE COALESCE((rbde.credit_stats).mean, 0.0) = bs.best_mean_credit
        )
        SELECT
            snapshot_slug, example_kind, files_hash, split,
            MAX(recall_denominator)::integer AS recall_denominator,
            critic_model,
            jsonb_agg(DISTINCT jsonb_build_object(
                'image_digest', critic_image_digest,
                'credit_stats', credit_stats,
                'n_runs', n_runs
            )) AS winning_definitions,
            best_mean_credit
        FROM ranked
        GROUP BY snapshot_slug, example_kind, files_hash, split, critic_model, best_mean_credit
    """)

    op.execute("""
        COMMENT ON VIEW pareto_frontier_by_example IS
        'Best definitions per example.'
    """)

    # =========================================================================
    # 9. get_validation_full_snapshot_aggregates — simplified
    # =========================================================================
    op.execute("""
        CREATE FUNCTION get_validation_full_snapshot_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            critic_image_digest text,
            critic_model text,
            critic_run_id uuid,
            status agent_run_status_enum,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
        DECLARE
            config jsonb;
        BEGIN
            config := current_agent_type_config();

            IF config IS NULL OR config->>'target_metric' != 'whole-repo' THEN
                RAISE EXCEPTION 'Access denied: get_validation_full_snapshot_aggregates() requires whole-repo target_metric';
            END IF;

            RETURN QUERY
            SELECT
                toc.snapshot_slug,
                toc.critic_image_digest,
                toc.critic_model,
                toc.critic_run_id,
                cr.status,
                SUM(toc.found_credit)::double precision AS total_credit,
                CAST(COUNT(*) AS integer) AS n_occurrences
            FROM tp_occurrence_credits toc
            JOIN snapshots s ON toc.snapshot_slug = s.slug
            JOIN agent_runs cr ON toc.critic_run_id = cr.agent_run_id
            WHERE s.split = 'valid'::split_enum
              AND toc.example_kind = 'whole_snapshot'
              AND (cr.type_config->>'agent_type') = 'critic'
            GROUP BY toc.snapshot_slug, toc.critic_image_digest, toc.critic_model,
                     toc.critic_run_id, cr.status
            ORDER BY toc.snapshot_slug, toc.critic_image_digest, toc.critic_model,
                     toc.critic_run_id;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION get_validation_full_snapshot_aggregates() IS
        'Black-box validation metrics for whole-repo mode.
Returns per-critic-run recall for VALID split, whole_snapshot example_kind only.
Requires caller to be a whole-repo mode agent (prompt_optimizer or improvement).'
    """)

    # =========================================================================
    # 10. validation_recall_by_definition — adapted to new function signature
    # =========================================================================
    op.execute("""
        CREATE VIEW validation_recall_by_definition AS
        SELECT
            critic_image_digest,
            critic_model,
            compute_stats_with_ci(array_agg(
                total_credit / NULLIF(n_occurrences, 0)
            )) AS recall_stats
        FROM get_validation_full_snapshot_aggregates()
        GROUP BY critic_image_digest, critic_model
    """)

    op.execute("""
        COMMENT ON VIEW validation_recall_by_definition IS
        'Aggregated validation recall by definition.'
    """)

    # =========================================================================
    # 11. Re-grant permissions
    # =========================================================================
    op.execute("GRANT SELECT ON TABLE tp_occurrence_credits TO agent_base")
    op.execute("GRANT SELECT ON TABLE occurrence_statistics TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_run TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_split_kind TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE pareto_frontier_by_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE validation_recall_by_definition TO agent_base")


def downgrade() -> None:
    """Reverse: drop new views, recreate old ones.

    This is complex due to the number of views. For simplicity, drop all new
    views and rely on re-running the complete schema migration to restore.
    """
    op.execute("DROP VIEW IF EXISTS validation_recall_by_definition")
    op.execute("DROP FUNCTION IF EXISTS get_validation_full_snapshot_aggregates()")
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example")
    op.execute("DROP VIEW IF EXISTS recall_by_example")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_split_kind")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_example")
    op.execute("DROP VIEW IF EXISTS recall_by_run")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics")
    op.execute("DROP VIEW IF EXISTS tp_occurrence_credits")
    # Old views would need to be recreated from 20251228000000_complete_schema.py
    # This downgrade only drops; full restore requires re-running that migration.
