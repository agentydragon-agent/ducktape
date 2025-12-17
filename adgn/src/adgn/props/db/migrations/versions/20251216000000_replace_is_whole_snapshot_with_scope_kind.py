"""Replace is_whole_snapshot with scope_kind in database views

Revision ID: 20251216000000
Revises: 20251215000000
Create Date: 2025-12-16 00:00:00.000000

Replaces the boolean is_whole_snapshot field with text scope_kind field
(computed as scope->>'kind') in all database views. This aligns with the
scope architecture migration where examples now store scope as a JSONB
discriminated union (AllFilesScope | ExplicitFileScope).

Views updated:
- occurrence_credits
- occurrence_run_credits
- aggregated_recall_by_prompt
- aggregated_recall_by_example
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251216000000"
down_revision: str | None = "20251219000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop function that depends on occurrence_credits
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    # Drop views in reverse dependency order
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")

    # Recreate occurrence_credits with scope_kind instead of is_whole_snapshot
    op.execute("""
        CREATE VIEW occurrence_credits AS
        -- Successful grader runs
        SELECT
            gr.id AS grader_run_id,
            gr.transcript_id AS grader_transcript_id,
            gr.created_at AS graded_at,
            gr.snapshot_slug,
            s.split,
            ex.scope_hash,
            ex.scope->>'kind' AS scope_kind,
            ex.scope AS reviewed_scope,
            cr.id AS critic_run_id,
            cr.transcript_id AS critic_transcript_id,
            cr.prompt_sha256,
            p.prompt_text,
            p.prompt_optimization_run_id,
            cr.model AS critic_model,
            gr.model AS grader_model,
            occ_result.value->>'tp_id' AS tp_id,
            occ_result.value->>'occurrence_id' AS occurrence_id,
            (occ_result.value->>'found_credit')::float AS found_credit,
            occ_result.value->'matched_by' AS matched_by_json,
            occ_result.value->>'rationale' AS grader_rationale
        FROM grader_runs gr
        JOIN critic_runs cr ON gr.critic_run_id = cr.id
        JOIN snapshots s ON gr.snapshot_slug = s.slug
        JOIN examples ex ON (
            cr.snapshot_slug = ex.snapshot_slug AND
            cr.scope_hash = ex.scope_hash
        )
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        CROSS JOIN LATERAL jsonb_array_elements(gr.output->'occurrence_results') occ_result
        WHERE gr.output->>'tag' = 'success'

        UNION ALL

        -- Critic failures (max_turns, context_length) as zero-credit
        SELECT
            NULL AS grader_run_id,
            NULL AS grader_transcript_id,
            cr.created_at AS graded_at,
            cr.snapshot_slug,
            s.split,
            ex.scope_hash,
            ex.scope->>'kind' AS scope_kind,
            ex.scope AS reviewed_scope,
            cr.id AS critic_run_id,
            cr.transcript_id AS critic_transcript_id,
            cr.prompt_sha256,
            p.prompt_text,
            p.prompt_optimization_run_id,
            cr.model AS critic_model,
            NULL AS grader_model,
            tp.tp_id,
            occ_data.value->>'occurrence_id' AS occurrence_id,
            0.0 AS found_credit,
            NULL AS matched_by_json,
            'Critic failed: ' || (cr.output->>'tag') AS grader_rationale
        FROM critic_runs cr
        JOIN snapshots s ON cr.snapshot_slug = s.slug
        JOIN examples ex ON (
            cr.snapshot_slug = ex.snapshot_slug AND
            cr.scope_hash = ex.scope_hash
        )
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        JOIN true_positives tp ON tp.snapshot_slug = ex.snapshot_slug
        CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) occ_data
        LEFT JOIN grader_runs gr_exists ON gr_exists.critic_run_id = cr.id
        WHERE cr.output->>'tag' IN ('max_turns_exceeded', 'context_length_exceeded')
          AND gr_exists.id IS NULL
          AND (
              ex.scope->>'kind' = 'entire_snapshot' OR
              EXISTS (
                  SELECT 1 FROM jsonb_array_elements(occ_data.value->'expect_caught_from') trigger_set
                  WHERE (
                      SELECT bool_and(file_elem.value IN (SELECT jsonb_array_elements_text(ex.scope->'files')))
                      FROM jsonb_array_elements_text(trigger_set.value) file_elem
                  )
              )
          )
    """)

    # Recreate occurrence_run_credits with scope_kind
    op.execute("""
        CREATE VIEW occurrence_run_credits AS
        SELECT
            split,
            snapshot_slug,
            scope_hash,
            scope_kind,
            tp_id,
            occurrence_id,
            critic_run_id,
            critic_model,
            prompt_sha256,
            AVG(found_credit) AS avg_credit,
            bool_or(grader_run_id IS NULL AND grader_rationale LIKE '%max_turns_exceeded%') AS is_max_turns_failure,
            bool_or(grader_run_id IS NULL AND grader_rationale LIKE '%context_length_exceeded%') AS is_context_failure
        FROM occurrence_credits
        GROUP BY split, snapshot_slug, scope_hash, scope_kind, tp_id, occurrence_id, critic_run_id, critic_model, prompt_sha256
    """)

    # Recreate aggregated_recall_by_example with scope_kind
    op.execute("""
        CREATE VIEW aggregated_recall_by_example AS
        SELECT
            split,
            snapshot_slug,
            scope_hash,
            critic_model,
            SUM(avg_credit) AS total_credit,
            COUNT(*) AS n_occurrences,
            SUM(avg_credit) / NULLIF(COUNT(*), 0) AS recall,
            COUNT(DISTINCT critic_run_id) AS n_critic_runs,
            COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) AS n_max_turns_exceeded,
            COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) AS n_context_length_exceeded
        FROM occurrence_run_credits
        GROUP BY split, snapshot_slug, scope_hash, critic_model
    """)

    # Recreate aggregated_recall_by_prompt with scope_kind
    op.execute("""
        CREATE VIEW aggregated_recall_by_prompt AS
        WITH per_run_recalls AS (
            SELECT
                split,
                prompt_sha256,
                critic_model,
                scope_kind,
                snapshot_slug,
                scope_hash,
                critic_run_id,
                SUM(avg_credit) AS total_credit,
                COUNT(*) AS n_occurrences,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) AS recall,
                bool_or(is_max_turns_failure) AS is_max_turns_failure,
                bool_or(is_context_failure) AS is_context_failure
            FROM occurrence_run_credits
            GROUP BY split, prompt_sha256, critic_model, scope_kind, snapshot_slug, scope_hash, critic_run_id
        )
        SELECT
            split,
            prompt_sha256,
            critic_model,
            scope_kind,
            SUM(total_credit) AS total_credit,
            SUM(n_occurrences) AS n_occurrences,
            AVG(recall) AS recall,
            COUNT(DISTINCT snapshot_slug) AS n_snapshots,
            COUNT(DISTINCT scope_hash) AS n_examples,
            COUNT(DISTINCT critic_run_id) AS n_runs,
            stddev(recall) AS recall_stddev,
            AVG(recall) + COALESCE(stddev(recall) / sqrt(COUNT(DISTINCT critic_run_id)), 0.0) AS ucb,
            AVG(recall) - COALESCE(stddev(recall) / sqrt(COUNT(DISTINCT critic_run_id)), 0.0) AS lcb,
            COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) AS n_max_turns_exceeded,
            COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) AS n_context_length_exceeded
        FROM per_run_recalls
        GROUP BY split, prompt_sha256, critic_model, scope_kind
    """)
    op.execute("""
        COMMENT ON VIEW aggregated_recall_by_prompt IS
        'Aggregates recall metrics by prompt across all examples and runs.
        Groups by scope_kind (discriminator from scope JSONB: entire_snapshot or specific_files).
        Includes sample size (n_examples, n_runs) and confidence bounds (ucb, lcb) for variance awareness.
        Per-run recall is computed first, then aggregated (stddev is stddev of per-run recalls).'
    """)

    # Recreate get_validation_run_aggregates function with scope_kind
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


def downgrade() -> None:
    # Drop function first
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    # Drop views in reverse dependency order
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")

    # Recreate original views with is_whole_snapshot
    op.execute("""
        CREATE VIEW occurrence_credits AS
        -- Successful grader runs
        SELECT
            gr.id AS grader_run_id,
            gr.transcript_id AS grader_transcript_id,
            gr.created_at AS graded_at,
            gr.snapshot_slug,
            s.split,
            ex.files_hash,
            ex.is_whole_snapshot,
            ex.files AS reviewed_files,
            gr.critique_id,
            cr.id AS critic_run_id,
            cr.transcript_id AS critic_transcript_id,
            cr.prompt_sha256,
            p.prompt_text,
            p.prompt_optimization_run_id,
            cr.model AS critic_model,
            gr.model AS grader_model,
            occ_result.value->>'tp_id' AS tp_id,
            occ_result.value->>'occurrence_id' AS occurrence_id,
            (occ_result.value->>'found_credit')::float AS found_credit,
            occ_result.value->'matched_by' AS matched_by_json,
            occ_result.value->>'rationale' AS grader_rationale
        FROM grader_runs gr
        JOIN critiques c ON gr.critique_id = c.id
        JOIN critic_runs cr ON c.id = cr.critique_id
        JOIN snapshots s ON gr.snapshot_slug = s.slug
        JOIN examples ex ON (
            cr.snapshot_slug = ex.snapshot_slug AND
            (cr.files_hash = ex.files_hash OR ex.is_whole_snapshot = true)
        )
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        CROSS JOIN LATERAL jsonb_array_elements(gr.output->'occurrence_results') occ_result
        WHERE gr.output->>'tag' = 'success'

        UNION ALL

        -- Critic failures (max_turns, context_length) as zero-credit
        SELECT
            NULL AS grader_run_id,
            NULL AS grader_transcript_id,
            cr.created_at AS graded_at,
            cr.snapshot_slug,
            s.split,
            ex.files_hash,
            ex.is_whole_snapshot,
            ex.files AS reviewed_files,
            NULL AS critique_id,
            cr.id AS critic_run_id,
            cr.transcript_id AS critic_transcript_id,
            cr.prompt_sha256,
            p.prompt_text,
            p.prompt_optimization_run_id,
            cr.model AS critic_model,
            NULL AS grader_model,
            tp.tp_id,
            occ_data.value->>'occurrence_id' AS occurrence_id,
            0.0 AS found_credit,
            NULL AS matched_by_json,
            'Critic failed: ' || (cr.output->>'tag') AS grader_rationale
        FROM critic_runs cr
        JOIN snapshots s ON cr.snapshot_slug = s.slug
        JOIN examples ex ON (
            cr.snapshot_slug = ex.snapshot_slug AND
            (cr.files_hash = ex.files_hash OR ex.is_whole_snapshot = true)
        )
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        JOIN true_positives tp ON tp.snapshot_slug = ex.snapshot_slug
        CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) occ_data
        WHERE cr.output->>'tag' IN ('max_turns_exceeded', 'context_length_exceeded')
          AND cr.critique_id IS NULL
          AND (
              ex.is_whole_snapshot = true OR
              EXISTS (
                  SELECT 1 FROM jsonb_array_elements(occ_data.value->'expect_caught_from') trigger_set
                  WHERE (
                      SELECT bool_and(file_elem.value IN (SELECT jsonb_array_elements_text(ex.files)))
                      FROM jsonb_array_elements_text(trigger_set.value) file_elem
                  )
              )
          )
    """)

    op.execute("""
        CREATE VIEW occurrence_run_credits AS
        SELECT
            split,
            snapshot_slug,
            files_hash,
            is_whole_snapshot,
            tp_id,
            occurrence_id,
            critic_run_id,
            critic_model,
            prompt_sha256,
            AVG(found_credit) AS avg_credit,
            bool_or(grader_run_id IS NULL AND grader_rationale LIKE '%max_turns_exceeded%') AS is_max_turns_failure,
            bool_or(grader_run_id IS NULL AND grader_rationale LIKE '%context_length_exceeded%') AS is_context_failure
        FROM occurrence_credits
        GROUP BY split, snapshot_slug, files_hash, is_whole_snapshot, tp_id, occurrence_id, critic_run_id, critic_model, prompt_sha256
    """)

    op.execute("""
        CREATE VIEW aggregated_recall_by_example AS
        SELECT
            split,
            snapshot_slug,
            files_hash,
            critic_model,
            SUM(avg_credit) AS total_credit,
            COUNT(*) AS n_occurrences,
            SUM(avg_credit) / NULLIF(COUNT(*), 0) AS recall,
            COUNT(DISTINCT critic_run_id) AS n_critic_runs,
            COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) AS n_max_turns_exceeded,
            COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) AS n_context_length_exceeded
        FROM occurrence_run_credits
        GROUP BY split, snapshot_slug, files_hash, critic_model
    """)

    op.execute("""
        CREATE VIEW aggregated_recall_by_prompt AS
        WITH per_run_recalls AS (
            SELECT
                split,
                prompt_sha256,
                critic_model,
                is_whole_snapshot,
                snapshot_slug,
                files_hash,
                critic_run_id,
                SUM(avg_credit) AS total_credit,
                COUNT(*) AS n_occurrences,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) AS recall,
                bool_or(is_max_turns_failure) AS is_max_turns_failure,
                bool_or(is_context_failure) AS is_context_failure
            FROM occurrence_run_credits
            GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot, snapshot_slug, files_hash, critic_run_id
        )
        SELECT
            split,
            prompt_sha256,
            critic_model,
            is_whole_snapshot,
            SUM(total_credit) AS total_credit,
            SUM(n_occurrences) AS n_occurrences,
            AVG(recall) AS recall,
            COUNT(DISTINCT snapshot_slug) AS n_snapshots,
            COUNT(DISTINCT files_hash) AS n_examples,
            COUNT(DISTINCT critic_run_id) AS n_runs,
            stddev(recall) AS recall_stddev,
            AVG(recall) + COALESCE(stddev(recall) / sqrt(COUNT(DISTINCT critic_run_id)), 0.0) AS ucb,
            AVG(recall) - COALESCE(stddev(recall) / sqrt(COUNT(DISTINCT critic_run_id)), 0.0) AS lcb,
            COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) AS n_max_turns_exceeded,
            COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) AS n_context_length_exceeded
        FROM per_run_recalls
        GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot
    """)
    op.execute("""
        COMMENT ON VIEW aggregated_recall_by_prompt IS
        'Aggregates recall metrics by prompt across all examples and runs.
        Includes sample size (n_examples, n_runs) and confidence bounds (ucb, lcb) for variance awareness.
        Per-run recall is computed first, then aggregated (stddev is stddev of per-run recalls).'
    """)

    # Recreate original get_validation_run_aggregates function
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
              AND oc.is_whole_snapshot = true
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
