"""Exclude in_progress critic runs from recall views.

Revision ID: 20251227000000
Revises: 20251226000002
Create Date: 2025-12-27

Problem: recall_by_run was including in_progress critic runs, counting them
as 0 credit. These runs haven't finished yet and shouldn't be in metrics at all.

Fix: Add `AND cr.status <> 'in_progress'` to the WHERE clause in recall_by_run.

IMPORTANT - CASCADE: Dropping recall_by_run cascades to:
- recall_by_definition_example
- recall_by_definition_split_kind
- recall_by_example
- pareto_frontier_by_example

All views must be recreated in correct dependency order.
"""

from alembic import op

revision = "20251227000000"
down_revision = "20251226000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop views in reverse dependency order (CASCADE handles this, but explicit for clarity)
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_split_kind CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_run CASCADE")

    # Recreate recall_by_run with in_progress filter
    # NOTE: Key change is `AND cr.status <> 'in_progress'` in the WHERE clause
    op.execute("""
        CREATE VIEW recall_by_run AS
        WITH grader_stats AS (
            SELECT
                gr.agent_run_id AS grader_run_id,
                get_graded_agent_run_id(gr.agent_run_id) AS critic_run_id,
                COALESCE(SUM(gd.credit) FILTER (WHERE gd.target_tp_id IS NOT NULL), 0.0) AS total_credit,
                COUNT(DISTINCT (gd.target_tp_id, gd.target_tp_occurrence_id))
                    FILTER (WHERE gd.target_tp_id IS NOT NULL) AS n_catchable
            FROM agent_runs gr
            JOIN grading_decisions gd ON gd.agent_run_id = gr.agent_run_id
            WHERE get_agent_type_config(gr.agent_run_id)->>'agent_type' = 'grader'
            GROUP BY gr.agent_run_id
        ),
        per_run AS (
            SELECT
                -- Example identification
                cr.type_config->'example'->>'snapshot_slug' AS snapshot_slug,
                e.example_kind,
                e.files_hash,
                s.split,
                e.n_catchable_occurrences,
                -- Critic-specific columns
                cr.agent_run_id AS critic_run_id,
                cr.agent_definition_id AS critic_definition_id,
                cr.model AS critic_model,
                cr.status AS critic_status,
                -- Totals-space stats over grader credits; failed critics default to 0 credit
                compute_stats_with_ci(
                    COALESCE(
                        array_agg(gs.total_credit) FILTER (WHERE cr.status = 'completed'),
                        ARRAY[0.0]::double precision[]
                    )
                ) AS credit_stats
            FROM agent_runs cr
            JOIN examples e ON (
                cr.type_config->'example'->>'snapshot_slug' = e.snapshot_slug
                AND (cr.type_config->'example'->>'kind')::example_kind_enum = e.example_kind
                AND COALESCE((cr.type_config->'example'->>'files_hash'), '') = COALESCE(e.files_hash, '')
            )
            JOIN snapshots s ON cr.type_config->'example'->>'snapshot_slug' = s.slug
            LEFT JOIN grader_stats gs ON gs.critic_run_id = cr.agent_run_id
            WHERE cr.type_config->>'agent_type' = 'critic'
              AND cr.status <> 'in_progress'  -- ADDED: Exclude in-progress runs
            GROUP BY cr.agent_run_id, cr.agent_definition_id, cr.type_config, s.split, cr.model, cr.status, e.example_kind, e.files_hash, e.n_catchable_occurrences
        )
        SELECT
            snapshot_slug,
            example_kind,
            files_hash,
            split,
            n_catchable_occurrences,
            critic_run_id,
            critic_definition_id,
            critic_model,
            critic_status,
            credit_stats,
            -- Recall derived by dividing credit by n_catchable_occurrences
            scale_stats(credit_stats, n_catchable_occurrences) AS recall_stats
        FROM per_run
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_run IS
        'Per-critic-run recall statistics aggregated over all graders.

Columns grouped by: example identification, then critic-specific, then statistics.

- n_catchable_occurrences: Ground truth count (denominator for recall)
- critic_status: Critic run status (completed, max_turns_exceeded, etc.)
- credit_stats: Stats over grader total credits (numerator; not normalized)
- recall_stats: credit_stats / n_catchable_occurrences via scale_stats()

NOTE: in_progress runs are excluded (they have not finished yet).
Failed critics (completed but no grader) contribute 0 credit via COALESCE.'
    """)

    # Recreate recall_by_definition_example
    op.execute("""
        CREATE VIEW recall_by_definition_example AS
        WITH raw_stats AS (
            SELECT
                rbr.critic_definition_id,
                rbr.critic_model,
                rbr.snapshot_slug,
                rbr.example_kind,
                rbr.files_hash,
                rbr.split,
                MAX(rbr.n_catchable_occurrences)::integer AS n_catchable_occurrences,
                COUNT(*)::integer AS n_runs,
                agg_status_counts(array_agg(rbr.critic_status)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((rbr.credit_stats).mean, 0.0)
                )) AS credit_stats
            FROM recall_by_run rbr
            GROUP BY rbr.critic_definition_id, rbr.critic_model,
                     rbr.snapshot_slug, rbr.example_kind, rbr.files_hash, rbr.split
        )
        SELECT
            critic_definition_id, critic_model,
            snapshot_slug, example_kind, files_hash, split,
            n_catchable_occurrences, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, n_catchable_occurrences) AS recall_stats
        FROM raw_stats
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_example IS
        'Per-(definition, model, example) recall statistics aggregated over all runs.

Intermediate view between recall_by_run and higher-level aggregations.
Used by GEPA to get recall for a specific (definition, model, example) tuple.

- n_catchable_occurrences: Ground truth count (denominator)
- n_runs: Number of critic runs for this (definition, model, example)
- credit_stats: Stats of raw credit counts across runs (numerator)
- recall_stats: credit_stats / n_catchable_occurrences via scale_stats()'
    """)

    # Recreate recall_by_definition_split_kind
    op.execute("""
        CREATE VIEW recall_by_definition_split_kind AS
        WITH
        -- Pre-aggregate per-example counts by grouping keys
        example_counts AS (
            SELECT
                split, example_kind, critic_definition_id, critic_model,
                COUNT(*)::integer AS n_examples,
                SUM(n_catchable_occurrences)::integer AS n_catchable_occurrences
            FROM (
                SELECT DISTINCT
                    split, example_kind, files_hash, n_catchable_occurrences,
                    critic_definition_id, critic_model
                FROM recall_by_definition_example
            ) per_example
            GROUP BY split, example_kind, critic_definition_id, critic_model
        ),
        -- Aggregate run-level stats
        run_stats AS (
            SELECT
                split, example_kind, critic_definition_id, critic_model,
                COUNT(*)::integer AS n_runs,
                agg_status_counts(array_agg(status_counts)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((credit_stats).mean, 0.0)
                )) AS credit_stats,
                COUNT(*) FILTER (WHERE COALESCE((credit_stats).mean, 0.0) = 0.0)::integer AS zero_count
            FROM recall_by_definition_example
            GROUP BY split, example_kind, critic_definition_id, critic_model
        )
        SELECT
            rs.split, rs.example_kind, rs.critic_definition_id, rs.critic_model,
            ec.n_examples, rs.n_runs, ec.n_catchable_occurrences,
            rs.status_counts, rs.credit_stats,
            scale_stats(rs.credit_stats, ec.n_catchable_occurrences) AS recall_stats,
            rs.zero_count
        FROM run_stats rs
        JOIN example_counts ec USING (split, example_kind, critic_definition_id, critic_model)
    """)

    op.execute("""
        COMMENT ON VIEW recall_by_definition_split_kind IS
        'Per-critic-definition aggregate metrics grouped by (definition, model, split, example_kind).

Aggregates recall_by_definition_example across examples within each (split, example_kind) group.

- n_catchable_occurrences: Sum across distinct examples (denominator)
- credit_stats: Stats of raw credit counts across runs (numerator); failed runs count as 0 credit
- recall_stats: credit_stats / n_catchable_occurrences via scale_stats()'
    """)

    # Recreate recall_by_example
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

    # Recreate pareto_frontier_by_example
    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH best_scores AS (
            SELECT
                snapshot_slug,
                split,
                example_kind,
                files_hash,
                n_catchable_occurrences,
                critic_model,
                max((credit_stats).mean) AS best_mean_credit
            FROM recall_by_definition_example
            GROUP BY snapshot_slug, split, example_kind, files_hash, n_catchable_occurrences, critic_model
        )
        SELECT
            bs.snapshot_slug,
            bs.split,
            bs.example_kind,
            bs.files_hash,
            bs.n_catchable_occurrences,
            bs.critic_model,
            -- Single column: list of winning definitions with their stats
            jsonb_agg(
                jsonb_build_object(
                    'definition_id', rbde.critic_definition_id,
                    'credit_stats', jsonb_build_object(
                        'n', (rbde.credit_stats).n,
                        'mean', (rbde.credit_stats).mean,
                        'min', (rbde.credit_stats).min,
                        'max', (rbde.credit_stats).max,
                        'lcb95', (rbde.credit_stats).lcb95,
                        'ucb95', (rbde.credit_stats).ucb95
                    ),
                    'n_runs', rbde.n_runs
                )
                ORDER BY rbde.critic_definition_id
            ) AS winning_definitions
        FROM best_scores bs
        JOIN recall_by_definition_example rbde ON (
            bs.snapshot_slug = rbde.snapshot_slug AND
            bs.split = rbde.split AND
            bs.example_kind = rbde.example_kind AND
            COALESCE(bs.files_hash, '') = COALESCE(rbde.files_hash, '') AND
            bs.critic_model = rbde.critic_model AND
            bs.best_mean_credit = (rbde.credit_stats).mean
        )
        GROUP BY bs.snapshot_slug, bs.split, bs.example_kind, bs.files_hash,
            bs.n_catchable_occurrences, bs.critic_model
    """)

    op.execute("""
        COMMENT ON VIEW pareto_frontier_by_example IS
        'Pareto frontier: definitions that achieved best mean credit on each example.

For each (snapshot_slug, split, example_kind, files_hash, critic_model), shows:
- n_catchable_occurrences: ground truth count (denominator for recall)
- winning_definitions: JSONB array of {definition_id, credit_stats} for all definitions at best score

All entries in winning_definitions have the same credit_stats.mean (the best score).
Consumer can compute recall as credit_stats.mean / n_catchable_occurrences.

Built on recall_by_definition_example, which aggregates over runs.
Failed critic runs (max_turns/context_length) count as 0.0 credit.'
    """)

    # Re-grant access to agent_base
    op.execute("GRANT SELECT ON TABLE recall_by_run TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_split_kind TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE pareto_frontier_by_example TO agent_base")


def downgrade() -> None:
    # Drop all views
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_split_kind CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_definition_example CASCADE")
    op.execute("DROP VIEW IF EXISTS recall_by_run CASCADE")

    # Recreate original recall_by_run without the in_progress filter
    op.execute("""
        CREATE VIEW recall_by_run AS
        WITH grader_stats AS (
            SELECT
                gr.agent_run_id AS grader_run_id,
                get_graded_agent_run_id(gr.agent_run_id) AS critic_run_id,
                COALESCE(SUM(gd.credit) FILTER (WHERE gd.target_tp_id IS NOT NULL), 0.0) AS total_credit,
                COUNT(DISTINCT (gd.target_tp_id, gd.target_tp_occurrence_id))
                    FILTER (WHERE gd.target_tp_id IS NOT NULL) AS n_catchable
            FROM agent_runs gr
            JOIN grading_decisions gd ON gd.agent_run_id = gr.agent_run_id
            WHERE get_agent_type_config(gr.agent_run_id)->>'agent_type' = 'grader'
            GROUP BY gr.agent_run_id
        ),
        per_run AS (
            SELECT
                cr.type_config->'example'->>'snapshot_slug' AS snapshot_slug,
                e.example_kind,
                e.files_hash,
                s.split,
                e.n_catchable_occurrences,
                cr.agent_run_id AS critic_run_id,
                cr.agent_definition_id AS critic_definition_id,
                cr.model AS critic_model,
                cr.status AS critic_status,
                compute_stats_with_ci(
                    COALESCE(
                        array_agg(gs.total_credit) FILTER (WHERE cr.status = 'completed'),
                        ARRAY[0.0]::double precision[]
                    )
                ) AS credit_stats
            FROM agent_runs cr
            JOIN examples e ON (
                cr.type_config->'example'->>'snapshot_slug' = e.snapshot_slug
                AND (cr.type_config->'example'->>'kind')::example_kind_enum = e.example_kind
                AND COALESCE((cr.type_config->'example'->>'files_hash'), '') = COALESCE(e.files_hash, '')
            )
            JOIN snapshots s ON cr.type_config->'example'->>'snapshot_slug' = s.slug
            LEFT JOIN grader_stats gs ON gs.critic_run_id = cr.agent_run_id
            WHERE cr.type_config->>'agent_type' = 'critic'
            GROUP BY cr.agent_run_id, cr.agent_definition_id, cr.type_config, s.split, cr.model, cr.status, e.example_kind, e.files_hash, e.n_catchable_occurrences
        )
        SELECT
            snapshot_slug,
            example_kind,
            files_hash,
            split,
            n_catchable_occurrences,
            critic_run_id,
            critic_definition_id,
            critic_model,
            critic_status,
            credit_stats,
            scale_stats(credit_stats, n_catchable_occurrences) AS recall_stats
        FROM per_run
    """)

    # Recreate other views (same as upgrade, they don't change)
    op.execute("""
        CREATE VIEW recall_by_definition_example AS
        WITH raw_stats AS (
            SELECT
                rbr.critic_definition_id,
                rbr.critic_model,
                rbr.snapshot_slug,
                rbr.example_kind,
                rbr.files_hash,
                rbr.split,
                MAX(rbr.n_catchable_occurrences)::integer AS n_catchable_occurrences,
                COUNT(*)::integer AS n_runs,
                agg_status_counts(array_agg(rbr.critic_status)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((rbr.credit_stats).mean, 0.0)
                )) AS credit_stats
            FROM recall_by_run rbr
            GROUP BY rbr.critic_definition_id, rbr.critic_model,
                     rbr.snapshot_slug, rbr.example_kind, rbr.files_hash, rbr.split
        )
        SELECT
            critic_definition_id, critic_model,
            snapshot_slug, example_kind, files_hash, split,
            n_catchable_occurrences, n_runs, status_counts, credit_stats,
            scale_stats(credit_stats, n_catchable_occurrences) AS recall_stats
        FROM raw_stats
    """)

    op.execute("""
        CREATE VIEW recall_by_definition_split_kind AS
        WITH
        example_counts AS (
            SELECT
                split, example_kind, critic_definition_id, critic_model,
                COUNT(*)::integer AS n_examples,
                SUM(n_catchable_occurrences)::integer AS n_catchable_occurrences
            FROM (
                SELECT DISTINCT
                    split, example_kind, files_hash, n_catchable_occurrences,
                    critic_definition_id, critic_model
                FROM recall_by_definition_example
            ) per_example
            GROUP BY split, example_kind, critic_definition_id, critic_model
        ),
        run_stats AS (
            SELECT
                split, example_kind, critic_definition_id, critic_model,
                COUNT(*)::integer AS n_runs,
                agg_status_counts(array_agg(status_counts)) AS status_counts,
                compute_stats_with_ci(array_agg(
                    COALESCE((credit_stats).mean, 0.0)
                )) AS credit_stats,
                COUNT(*) FILTER (WHERE COALESCE((credit_stats).mean, 0.0) = 0.0)::integer AS zero_count
            FROM recall_by_definition_example
            GROUP BY split, example_kind, critic_definition_id, critic_model
        )
        SELECT
            rs.split, rs.example_kind, rs.critic_definition_id, rs.critic_model,
            ec.n_examples, rs.n_runs, ec.n_catchable_occurrences,
            rs.status_counts, rs.credit_stats,
            scale_stats(rs.credit_stats, ec.n_catchable_occurrences) AS recall_stats,
            rs.zero_count
        FROM run_stats rs
        JOIN example_counts ec USING (split, example_kind, critic_definition_id, critic_model)
    """)

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

    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH best_scores AS (
            SELECT
                snapshot_slug,
                split,
                example_kind,
                files_hash,
                n_catchable_occurrences,
                critic_model,
                max((credit_stats).mean) AS best_mean_credit
            FROM recall_by_definition_example
            GROUP BY snapshot_slug, split, example_kind, files_hash, n_catchable_occurrences, critic_model
        )
        SELECT
            bs.snapshot_slug,
            bs.split,
            bs.example_kind,
            bs.files_hash,
            bs.n_catchable_occurrences,
            bs.critic_model,
            jsonb_agg(
                jsonb_build_object(
                    'definition_id', rbde.critic_definition_id,
                    'credit_stats', jsonb_build_object(
                        'n', (rbde.credit_stats).n,
                        'mean', (rbde.credit_stats).mean,
                        'min', (rbde.credit_stats).min,
                        'max', (rbde.credit_stats).max,
                        'lcb95', (rbde.credit_stats).lcb95,
                        'ucb95', (rbde.credit_stats).ucb95
                    ),
                    'n_runs', rbde.n_runs
                )
                ORDER BY rbde.critic_definition_id
            ) AS winning_definitions
        FROM best_scores bs
        JOIN recall_by_definition_example rbde ON (
            bs.snapshot_slug = rbde.snapshot_slug AND
            bs.split = rbde.split AND
            bs.example_kind = rbde.example_kind AND
            COALESCE(bs.files_hash, '') = COALESCE(rbde.files_hash, '') AND
            bs.critic_model = rbde.critic_model AND
            bs.best_mean_credit = (rbde.credit_stats).mean
        )
        GROUP BY bs.snapshot_slug, bs.split, bs.example_kind, bs.files_hash,
            bs.n_catchable_occurrences, bs.critic_model
    """)

    # Re-grant access
    op.execute("GRANT SELECT ON TABLE recall_by_run TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_definition_split_kind TO agent_base")
    op.execute("GRANT SELECT ON TABLE recall_by_example TO agent_base")
    op.execute("GRANT SELECT ON TABLE pareto_frontier_by_example TO agent_base")
