"""Recreate views to use agent_runs instead of critic_runs/grader_runs.

This migration updates all views that previously joined critic_runs and grader_runs
to instead use agent_runs with type filtering via type_config->>'agent_type'.

Views being updated:
- occurrence_credits
- occurrence_run_credits
- occurrence_statistics
- critic_run_occurrence_stats
- aggregated_recall_by_definition (was aggregated_recall_by_prompt)
- aggregated_recall_by_example
- pareto_frontier_by_example
- get_validation_run_aggregates() function

Key changes:
- Replace "FROM critic_runs cr" with "FROM agent_runs cr WHERE (cr.type_config->>'agent_type') = 'critic'"
- Replace "FROM grader_runs gr" with "FROM agent_runs gr WHERE (gr.type_config->>'agent_type') = 'grader'"
- Use agent_run_id as the primary key (was 'id' in legacy tables)
- Use type_config->>'snapshot_slug' for critic's snapshot
- Use type_config->>'graded_agent_run_id' for grader's critic reference
- Replace prompt_sha256/prompts with agent_definition_id/agent_definitions

Revision ID: 20251226000002
Revises: 20251226000001
Create Date: 2025-12-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251226000002"
down_revision: str | Sequence[str] | None = "20251226000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recreate all views to use agent_runs instead of critic_runs/grader_runs."""
    # Step 1: Drop all dependent views and function in reverse dependency order
    # CASCADE handles most dependencies, but let's be explicit
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_definition CASCADE")
    op.execute("DROP VIEW IF EXISTS critic_run_occurrence_stats CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")

    # Step 2: Recreate occurrence_credits using agent_runs
    # Uses agent_definition_id instead of prompt_sha256
    op.execute("""
        CREATE VIEW occurrence_credits AS
        -- Successful grader runs: Read from normalized grading_decisions table
        SELECT
            gr.agent_run_id AS grader_run_id,
            gr.agent_run_id AS grader_transcript_id,
            gr.created_at AS graded_at,
            cr.type_config->>'snapshot_slug' AS snapshot_slug,
            s.split,
            cr.type_config->>'scope_hash' AS scope_hash,
            (ex.scope->>'kind') AS scope_kind,
            ex.scope AS reviewed_scope,
            cr.agent_run_id AS critic_run_id,
            cr.agent_run_id AS critic_transcript_id,
            cr.agent_definition_id,
            cr.model AS critic_model,
            gr.model AS grader_model,
            gd.target_tp_id AS tp_id,
            gd.target_tp_occurrence_id AS occurrence_id,
            SUM(gd.credit) AS found_credit,
            jsonb_agg(gd.input_issue_id ORDER BY gd.input_issue_id) AS matched_by_json,
            MAX(gd.rationale) AS grader_rationale
        FROM agent_runs gr
        -- Join to get the critic run being graded
        JOIN agent_runs cr ON cr.agent_run_id = (gr.type_config->>'graded_agent_run_id')::UUID
        JOIN snapshots s ON (cr.type_config->>'snapshot_slug') = s.slug
        JOIN examples ex ON (cr.type_config->>'snapshot_slug') = ex.snapshot_slug
                        AND (cr.type_config->>'scope_hash') = ex.scope_hash
        JOIN grading_decisions gd ON gr.agent_run_id = gd.agent_run_id
        WHERE (gr.type_config->>'agent_type') = 'grader'
          AND (cr.type_config->>'agent_type') = 'critic'
          AND gd.target_tp_id IS NOT NULL
        GROUP BY gr.agent_run_id, gr.created_at,
                 cr.type_config->>'snapshot_slug', s.split,
                 cr.type_config->>'scope_hash', ex.scope,
                 cr.agent_run_id, cr.agent_definition_id,
                 cr.model, gr.model,
                 gd.target_tp_id, gd.target_tp_occurrence_id

        UNION ALL

        -- Failed critic runs (no grader run): Read from true_positives.occurrences JSONB
        -- Use proper catchability logic based on expect_caught_from
        SELECT
            NULL::uuid AS grader_run_id,
            NULL::uuid AS grader_transcript_id,
            cr.created_at AS graded_at,
            cr.type_config->>'snapshot_slug' AS snapshot_slug,
            s.split,
            cr.type_config->>'scope_hash' AS scope_hash,
            (ex.scope->>'kind') AS scope_kind,
            ex.scope AS reviewed_scope,
            cr.agent_run_id AS critic_run_id,
            cr.agent_run_id AS critic_transcript_id,
            cr.agent_definition_id,
            cr.model AS critic_model,
            NULL::varchar AS grader_model,
            tp.tp_id,
            occ_data.value->>'occurrence_id' AS occurrence_id,
            0.0 AS found_credit,
            NULL::jsonb AS matched_by_json,
            'Critic failed: ' || cr.status AS grader_rationale
        FROM agent_runs cr
        JOIN snapshots s ON (cr.type_config->>'snapshot_slug') = s.slug
        JOIN examples ex ON (cr.type_config->>'snapshot_slug') = ex.snapshot_slug
                        AND (cr.type_config->>'scope_hash') = ex.scope_hash
        CROSS JOIN true_positives tp
        CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) AS occ_data(value)
        WHERE (cr.type_config->>'agent_type') = 'critic'
          AND cr.status IN ('max_turns_exceeded', 'context_length_exceeded')
          AND (cr.type_config->>'snapshot_slug') = tp.snapshot_slug
          AND (
              -- AllFilesScope (entire_snapshot): include all occurrences
              (ex.scope->>'kind') = 'entire_snapshot'
              OR
              -- ExplicitFileScope (specific_files): check if ANY trigger set is a subset of reviewed files
              EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(occ_data.value->'expect_caught_from') AS trigger_set
                  WHERE (
                      SELECT bool_and(file_elem IN (SELECT jsonb_array_elements_text(ex.scope->'files')))
                      FROM jsonb_array_elements_text(trigger_set) AS file_elem
                  )
              )
          )
    """)

    op.execute("""
        COMMENT ON VIEW occurrence_credits IS
        'Per-occurrence credit assignments from grader decisions or failed critic runs.
        Now uses agent_runs table with type filtering instead of legacy critic_runs/grader_runs.
        Uses agent_definition_id instead of prompt_sha256.

        For successful grading: joins grader agent_run to critic agent_run via type_config->graded_agent_run_id.
        For failed critics: synthesizes zero-credit rows for catchable occurrences.'
    """)

    # Step 3: Recreate occurrence_run_credits
    op.execute("""
        CREATE VIEW occurrence_run_credits AS
        SELECT
            grader_run_id,
            grader_transcript_id,
            graded_at,
            snapshot_slug,
            split,
            scope_hash,
            scope_kind,
            reviewed_scope,
            critic_run_id,
            critic_transcript_id,
            agent_definition_id,
            critic_model,
            grader_model,
            tp_id,
            occurrence_id,
            AVG(found_credit) AS avg_credit,
            ARRAY_AGG(DISTINCT matched_by_json) FILTER (WHERE matched_by_json IS NOT NULL) AS all_matched_by,
            STRING_AGG(DISTINCT grader_rationale, ' | ') AS combined_rationale
        FROM occurrence_credits
        GROUP BY grader_run_id, grader_transcript_id, graded_at, snapshot_slug, split,
                 scope_hash, scope_kind, reviewed_scope, critic_run_id, critic_transcript_id,
                 agent_definition_id, critic_model,
                 grader_model, tp_id, occurrence_id
    """)

    # Step 4: Recreate occurrence_statistics
    op.execute("""
        CREATE VIEW occurrence_statistics AS
        SELECT
            snapshot_slug,
            split,
            scope_hash,
            scope_kind,
            reviewed_scope,
            agent_definition_id,
            critic_model,
            grader_model,
            tp_id,
            occurrence_id,
            COUNT(DISTINCT grader_run_id) AS n_grader_runs,
            AVG(avg_credit) AS mean_credit,
            STDDEV_POP(avg_credit) AS stddev_credit,
            MIN(avg_credit) AS min_credit,
            MAX(avg_credit) AS max_credit
        FROM occurrence_run_credits
        GROUP BY snapshot_slug, split, scope_hash, scope_kind, reviewed_scope,
                 agent_definition_id,
                 critic_model, grader_model, tp_id, occurrence_id
    """)

    # Step 5: Recreate critic_run_occurrence_stats using agent_runs
    op.execute("""
        CREATE VIEW critic_run_occurrence_stats AS
        SELECT
            cr.agent_run_id as critic_run_id,
            cr.agent_definition_id,
            cr.type_config->>'snapshot_slug' AS snapshot_slug,
            cr.type_config->>'scope_hash' AS scope_hash,
            s.split,
            cr.model as critic_model,
            cr.status,
            e.scope->>'kind' AS scope_kind,

            -- Average occurrences caught across graders (from normalized grading_decisions)
            AVG(
                CASE
                    WHEN cr.status = 'completed' AND gr.agent_run_id IS NOT NULL THEN (
                        SELECT COALESCE(SUM(gd.credit), 0.0)
                        FROM grading_decisions gd
                        WHERE gd.agent_run_id = gr.agent_run_id
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
                    WHERE gd.agent_run_id = (
                        SELECT gr2.agent_run_id
                        FROM agent_runs gr2
                        WHERE (gr2.type_config->>'agent_type') = 'grader'
                          AND (gr2.type_config->>'graded_agent_run_id')::UUID = cr.agent_run_id
                        LIMIT 1
                    )
                    AND gd.target_tp_id IS NOT NULL
                ),
                0
            ) as n_catchable_occurrences,

            -- Count how many graders ran on this critic run
            COUNT(gr.agent_run_id) as n_grader_runs

        FROM agent_runs cr
        JOIN examples e ON (cr.type_config->>'snapshot_slug') = e.snapshot_slug
                       AND (cr.type_config->>'scope_hash') = e.scope_hash
        JOIN snapshots s ON (cr.type_config->>'snapshot_slug') = s.slug
        LEFT JOIN agent_runs gr ON (gr.type_config->>'agent_type') = 'grader'
                               AND (gr.type_config->>'graded_agent_run_id')::UUID = cr.agent_run_id

        WHERE (cr.type_config->>'agent_type') = 'critic'

        GROUP BY cr.agent_run_id, cr.agent_definition_id, cr.type_config, s.split, cr.model, cr.status, e.scope
    """)

    op.execute("""
        COMMENT ON VIEW critic_run_occurrence_stats IS
        'Per-critic-run occurrence statistics aggregated over all graders.
        Now uses agent_runs with type filtering instead of legacy critic_runs/grader_runs.
        Uses agent_definition_id instead of prompt_sha256.

        Intermediate view that computes:
        - avg_occurrences_caught: Average raw occurrence count across graders for this run
        - n_catchable_occurrences: Total occurrences that could be caught (computed once)
        - n_grader_runs: How many graders ran on this critic run
        - scope_kind: Scope type (entire_snapshot or explicit_files)

        Failed critic runs (max_turns/context_length) have avg_occurrences_caught = NULL.'
    """)

    # Step 6: Recreate aggregated_recall_by_definition (was aggregated_recall_by_prompt)
    op.execute("""
        CREATE VIEW aggregated_recall_by_definition AS
        SELECT
            agent_definition_id,
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
        GROUP BY agent_definition_id, split, critic_model, scope_kind
    """)

    op.execute("""
        COMMENT ON VIEW aggregated_recall_by_definition IS
        'Per-agent-definition aggregate metrics with occurrence-based weighting, averaged over all grader models.
        Replaces aggregated_recall_by_prompt - uses agent_definition_id instead of prompt_sha256.

        OCCURRENCE-BASED WEIGHTING: This view computes raw occurrence counts (not percentages).
        When computing dataset-level recall, sum avg_occurrences_caught and sum total_catchable_occurrences
        across rows, then divide: SUM(avg_occurrences_caught) / SUM(total_catchable_occurrences).
        This naturally weights examples by their occurrence count (20 occurrences = 20x weight of 1 occurrence).'
    """)

    # Step 7: Recreate aggregated_recall_by_example
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

    # Step 8: Recreate pareto_frontier_by_example
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
                cros.agent_definition_id,
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
        avg_recall_per_definition_example AS (
            -- Average recall across runs for each (snapshot, scope_hash, agent_definition)
            SELECT
                split,
                snapshot_slug,
                scope_hash,
                scope_kind,
                agent_definition_id,
                critic_model,
                AVG(recall) AS avg_recall,
                COUNT(DISTINCT critic_run_id) AS n_runs
            FROM per_run_recalls
            GROUP BY split, snapshot_slug, scope_hash, scope_kind, agent_definition_id, critic_model
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
            FROM avg_recall_per_definition_example
            GROUP BY split, snapshot_slug, scope_hash, scope_kind, critic_model
        )
        SELECT
            bs.split,
            bs.snapshot_slug,
            bs.scope_hash,
            bs.scope_kind,
            bs.critic_model,
            bs.best_recall,
            array_agg(arpde.agent_definition_id ORDER BY arpde.agent_definition_id) AS winning_definition_ids,
            array_agg(arpde.n_runs ORDER BY arpde.agent_definition_id) AS winning_definition_n_runs
        FROM best_scores bs
        JOIN avg_recall_per_definition_example arpde ON
            bs.split = arpde.split AND
            bs.snapshot_slug = arpde.snapshot_slug AND
            bs.scope_hash = arpde.scope_hash AND
            bs.scope_kind = arpde.scope_kind AND
            bs.critic_model = arpde.critic_model AND
            bs.best_recall = arpde.avg_recall
        GROUP BY bs.split, bs.snapshot_slug, bs.scope_hash, bs.scope_kind, bs.critic_model, bs.best_recall
    """)

    op.execute("""
        COMMENT ON VIEW pareto_frontier_by_example IS
        'Pareto frontier: best recall achieved on each example and which agent definitions achieved it.
        Now uses agent_runs with type filtering instead of legacy critic_runs/grader_runs.
        Uses agent_definition_id instead of prompt_sha256.

        Uses occurrence-based weighting: recall = occurrences_caught / catchable_occurrences.
        This naturally weights examples by their issue density (20 occurrences = 20x weight of 1 occurrence).

        For each (split, snapshot_slug, scope_hash, critic_model), shows the best average recall
        across all definitions and lists all definition IDs that achieved this best score.

        Built on critic_run_occurrence_stats, which already aggregates over grader models.
        Failed critic runs (max_turns/context_length) count as 0.0 recall.'
    """)

    # Step 9: Recreate get_validation_run_aggregates() function
    op.execute("""
        CREATE FUNCTION get_validation_run_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            agent_definition_id text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status agent_run_status_enum,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.agent_definition_id,
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
            JOIN agent_runs cr ON oc.critic_run_id = cr.agent_run_id
            WHERE s.split = 'valid'::split_enum
              AND oc.scope_kind = 'entire_snapshot'
              AND (cr.type_config->>'agent_type') = 'critic'
            GROUP BY oc.snapshot_slug, oc.agent_definition_id, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, cr.status, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            agent_definition_id,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            status,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, agent_definition_id, critic_model, grader_model,
                   critic_run_id, grader_run_id, status
          ORDER BY snapshot_slug, agent_definition_id, critic_model, grader_model,
                   critic_run_id, grader_run_id
        $$;
    """)

    op.execute("""
        COMMENT ON FUNCTION get_validation_run_aggregates() IS
        'Black-box validation metrics for whole-repo mode.
        Now uses agent_runs with type filtering instead of legacy critic_runs table.
        Uses agent_definition_id instead of prompt_sha256.
        Returns per-run recall for VALID split, entire_snapshot scope_kind only.
        Includes critic_run status for proper outcome counting.
        Used by prompt optimizer in whole-repo validation mode.'
    """)

    # Step 10: Grant SELECT on views to agent_base role
    op.execute("""
        GRANT SELECT ON occurrence_credits TO agent_base;
        GRANT SELECT ON occurrence_run_credits TO agent_base;
        GRANT SELECT ON occurrence_statistics TO agent_base;
        GRANT SELECT ON critic_run_occurrence_stats TO agent_base;
        GRANT SELECT ON aggregated_recall_by_definition TO agent_base;
        GRANT SELECT ON aggregated_recall_by_example TO agent_base;
        GRANT SELECT ON pareto_frontier_by_example TO agent_base;
        GRANT EXECUTE ON FUNCTION get_validation_run_aggregates() TO agent_base;
    """)


def downgrade() -> None:
    """Restore views to use critic_runs/grader_runs tables.

    NOTE: This downgrade still uses agent_run_id for grading_decisions
    (not grader_run_id) because the grading_decisions migration runs
    AFTER this one during downgrade. The views join via gr.id matching
    the grading_decisions.agent_run_id through the grader_runs.transcript_id
    relationship.

    Also restores prompt_sha256/prompts instead of agent_definition_id.
    """
    # Drop all agent_runs-based views
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_definition CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS critic_run_occurrence_stats CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")

    # Recreate occurrence_credits using critic_runs/grader_runs tables
    # but with grading_decisions.agent_run_id (since that column still exists
    # until 20251226000000 downgrade runs)
    op.execute("""
        CREATE VIEW occurrence_credits AS
        -- Successful grader runs: Read from normalized grading_decisions table
        -- Note: grading_decisions uses agent_run_id which matches grader_runs.transcript_id
        SELECT
            gr.id AS grader_run_id,
            gr.transcript_id AS grader_transcript_id,
            gr.created_at AS graded_at,
            gr.snapshot_slug,
            s.split,
            ex.scope_hash,
            (ex.scope->>'kind') AS scope_kind,
            ex.scope AS reviewed_scope,
            cr.id AS critic_run_id,
            cr.transcript_id AS critic_transcript_id,
            cr.prompt_sha256,
            p.prompt_text,
            p.prompt_optimization_run_id,
            cr.model AS critic_model,
            gr.model AS grader_model,
            gd.target_tp_id AS tp_id,
            gd.target_tp_occurrence_id AS occurrence_id,
            SUM(gd.credit) AS found_credit,
            jsonb_agg(gd.input_issue_id ORDER BY gd.input_issue_id) AS matched_by_json,
            MAX(gd.rationale) AS grader_rationale
        FROM grader_runs gr
        JOIN critic_runs cr ON gr.critic_run_id = cr.id
        JOIN snapshots s ON gr.snapshot_slug = s.slug
        JOIN examples ex ON cr.snapshot_slug = ex.snapshot_slug AND cr.scope_hash = ex.scope_hash
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        JOIN grading_decisions gd ON gr.transcript_id = gd.agent_run_id
        WHERE gd.target_tp_id IS NOT NULL
        GROUP BY gr.id, gr.transcript_id, gr.created_at, gr.snapshot_slug, s.split,
                 ex.scope_hash, ex.scope, cr.id, cr.transcript_id, cr.prompt_sha256,
                 p.prompt_text, p.prompt_optimization_run_id, cr.model, gr.model,
                 gd.target_tp_id, gd.target_tp_occurrence_id

        UNION ALL

        -- Failed critic runs (no grader run): Read from true_positives.occurrences JSONB
        SELECT
            NULL::uuid AS grader_run_id,
            NULL::uuid AS grader_transcript_id,
            cr.created_at AS graded_at,
            cr.snapshot_slug,
            s.split,
            ex.scope_hash,
            (ex.scope->>'kind') AS scope_kind,
            ex.scope AS reviewed_scope,
            cr.id AS critic_run_id,
            cr.transcript_id AS critic_transcript_id,
            cr.prompt_sha256,
            p.prompt_text,
            p.prompt_optimization_run_id,
            cr.model AS critic_model,
            NULL::varchar AS grader_model,
            tp.tp_id,
            occ_data.value->>'occurrence_id' AS occurrence_id,
            0.0 AS found_credit,
            NULL::jsonb AS matched_by_json,
            'Critic failed: ' || cr.status AS grader_rationale
        FROM critic_runs cr
        JOIN snapshots s ON cr.snapshot_slug = s.slug
        JOIN examples ex ON cr.snapshot_slug = ex.snapshot_slug AND cr.scope_hash = ex.scope_hash
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        CROSS JOIN true_positives tp
        CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) AS occ_data(value)
        WHERE cr.status IN ('max_turns_exceeded', 'context_length_exceeded')
          AND cr.snapshot_slug = tp.snapshot_slug
          AND (
              (ex.scope->>'kind') = 'entire_snapshot'
              OR
              EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(occ_data.value->'expect_caught_from') AS trigger_set
                  WHERE (
                      SELECT bool_and(file_elem IN (SELECT jsonb_array_elements_text(ex.scope->'files')))
                      FROM jsonb_array_elements_text(trigger_set) AS file_elem
                  )
              )
          )
    """)

    # Recreate occurrence_run_credits
    op.execute("""
        CREATE VIEW occurrence_run_credits AS
        SELECT
            grader_run_id,
            grader_transcript_id,
            graded_at,
            snapshot_slug,
            split,
            scope_hash,
            scope_kind,
            reviewed_scope,
            critic_run_id,
            critic_transcript_id,
            prompt_sha256,
            prompt_text,
            prompt_optimization_run_id,
            critic_model,
            grader_model,
            tp_id,
            occurrence_id,
            AVG(found_credit) AS avg_credit,
            ARRAY_AGG(DISTINCT matched_by_json) FILTER (WHERE matched_by_json IS NOT NULL) AS all_matched_by,
            STRING_AGG(DISTINCT grader_rationale, ' | ') AS combined_rationale
        FROM occurrence_credits
        GROUP BY grader_run_id, grader_transcript_id, graded_at, snapshot_slug, split,
                 scope_hash, scope_kind, reviewed_scope, critic_run_id, critic_transcript_id,
                 prompt_sha256, prompt_text, prompt_optimization_run_id, critic_model,
                 grader_model, tp_id, occurrence_id
    """)

    # Recreate occurrence_statistics
    op.execute("""
        CREATE VIEW occurrence_statistics AS
        SELECT
            snapshot_slug,
            split,
            scope_hash,
            scope_kind,
            reviewed_scope,
            prompt_sha256,
            prompt_text,
            prompt_optimization_run_id,
            critic_model,
            grader_model,
            tp_id,
            occurrence_id,
            COUNT(DISTINCT grader_run_id) AS n_grader_runs,
            AVG(avg_credit) AS mean_credit,
            STDDEV_POP(avg_credit) AS stddev_credit,
            MIN(avg_credit) AS min_credit,
            MAX(avg_credit) AS max_credit
        FROM occurrence_run_credits
        GROUP BY snapshot_slug, split, scope_hash, scope_kind, reviewed_scope,
                 prompt_sha256, prompt_text, prompt_optimization_run_id,
                 critic_model, grader_model, tp_id, occurrence_id
    """)

    # Recreate critic_run_occurrence_stats
    # Note: grading_decisions uses agent_run_id (matching grader_runs.transcript_id)
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

            AVG(
                CASE
                    WHEN cr.status = 'completed' AND gr.id IS NOT NULL THEN (
                        SELECT COALESCE(SUM(gd.credit), 0.0)
                        FROM grading_decisions gd
                        WHERE gd.agent_run_id = gr.transcript_id
                          AND gd.target_tp_id IS NOT NULL
                    )
                    ELSE NULL
                END
            ) as avg_occurrences_caught,

            COALESCE(
                (
                    SELECT COUNT(DISTINCT (gd.target_tp_id, gd.target_tp_occurrence_id))::integer
                    FROM grading_decisions gd
                    WHERE gd.agent_run_id = (
                        SELECT transcript_id FROM grader_runs WHERE critic_run_id = cr.id LIMIT 1
                    )
                    AND gd.target_tp_id IS NOT NULL
                ),
                0
            ) as n_catchable_occurrences,

            COUNT(gr.id) as n_grader_runs

        FROM critic_runs cr
        JOIN examples e ON (cr.snapshot_slug, cr.scope_hash) = (e.snapshot_slug, e.scope_hash)
        JOIN snapshots s ON e.snapshot_slug = s.slug
        LEFT JOIN grader_runs gr ON gr.critic_run_id = cr.id

        GROUP BY cr.id, cr.prompt_sha256, cr.snapshot_slug, cr.scope_hash, s.split, cr.model, cr.status, e.scope
    """)

    # Recreate aggregated_recall_by_prompt
    op.execute("""
        CREATE VIEW aggregated_recall_by_prompt AS
        SELECT
            prompt_sha256,
            split,
            critic_model,
            scope_kind,

            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)::integer as n_successful,
            SUM(CASE WHEN status = 'max_turns_exceeded' THEN 1 ELSE 0 END)::integer as n_max_turns_exceeded,
            SUM(CASE WHEN status = 'context_length_exceeded' THEN 1 ELSE 0 END)::integer as n_context_length_exceeded,
            SUM(CASE WHEN status = 'reported_failure' THEN 1 ELSE 0 END)::integer as n_reported_failure,

            COUNT(DISTINCT (snapshot_slug, scope_hash))::integer as n_examples,
            COUNT(*)::integer as n_runs,

            AVG(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as avg_occurrences_caught_among_successful,
            VAR_SAMP(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as occurrences_variance_among_successful,

            AVG(COALESCE(avg_occurrences_caught, 0.0)) as avg_occurrences_caught_overall,

            AVG(n_catchable_occurrences) as avg_catchable_occurrences,
            SUM(n_catchable_occurrences)::integer as total_catchable_occurrences,

            CASE
                WHEN AVG(n_catchable_occurrences) > 0
                THEN AVG(COALESCE(avg_occurrences_caught, 0.0)) / AVG(n_catchable_occurrences)
                ELSE NULL
            END as recall,

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

            AVG(n_grader_runs) as avg_grader_runs_per_critic,
            SUM(n_grader_runs)::integer as total_grader_runs

        FROM critic_run_occurrence_stats
        GROUP BY prompt_sha256, split, critic_model, scope_kind
    """)

    # Recreate aggregated_recall_by_example
    op.execute("""
        CREATE VIEW aggregated_recall_by_example AS
        SELECT
            snapshot_slug,
            scope_hash,
            split,
            critic_model,

            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)::integer as n_successful,
            SUM(CASE WHEN status = 'max_turns_exceeded' THEN 1 ELSE 0 END)::integer as n_max_turns_exceeded,
            SUM(CASE WHEN status = 'context_length_exceeded' THEN 1 ELSE 0 END)::integer as n_context_length_exceeded,
            SUM(CASE WHEN status = 'reported_failure' THEN 1 ELSE 0 END)::integer as n_reported_failure,

            COUNT(*)::integer as n_runs,

            AVG(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as avg_occurrences_caught_among_successful,
            VAR_SAMP(CASE WHEN status = 'completed' THEN avg_occurrences_caught ELSE NULL END)
                as occurrences_variance_among_successful,
            AVG(COALESCE(avg_occurrences_caught, 0.0)) as avg_occurrences_caught_overall,

            AVG(n_catchable_occurrences) as avg_catchable_occurrences,
            SUM(n_catchable_occurrences)::integer as total_catchable_occurrences,

            CASE
                WHEN AVG(n_catchable_occurrences) > 0
                THEN AVG(COALESCE(avg_occurrences_caught, 0.0)) / AVG(n_catchable_occurrences)
                ELSE NULL
            END as recall,

            AVG(n_grader_runs) as avg_grader_runs_per_critic,
            SUM(n_grader_runs)::integer as total_grader_runs

        FROM critic_run_occurrence_stats
        GROUP BY snapshot_slug, scope_hash, split, critic_model
    """)

    # Recreate pareto_frontier_by_example
    op.execute("""
        CREATE VIEW pareto_frontier_by_example AS
        WITH per_run_recalls AS (
            SELECT
                cros.split,
                cros.snapshot_slug,
                cros.scope_hash,
                cros.scope_kind,
                cros.prompt_sha256,
                cros.critic_run_id,
                cros.critic_model,
                CASE
                    WHEN cros.n_catchable_occurrences > 0
                    THEN COALESCE(cros.avg_occurrences_caught, 0.0) / cros.n_catchable_occurrences
                    ELSE 0.0
                END AS recall
            FROM critic_run_occurrence_stats cros
        ),
        avg_recall_per_prompt_example AS (
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

    # Recreate get_validation_run_aggregates()
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
