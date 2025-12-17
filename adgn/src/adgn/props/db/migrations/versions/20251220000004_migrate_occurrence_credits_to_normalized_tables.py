"""migrate_occurrence_credits_to_normalized_tables

Revision ID: 20251220000004
Revises: 20251220000003
Create Date: 2025-12-16 16:56:23.767569

Migrates occurrence_credits view to read from normalized grading_decisions table
instead of JSONB gr.output. This completes the migration from JSONB-stored grading
results to normalized tables.

Note: The second part (failed critic runs) still reads true_positives.occurrences
JSONB because normalizing TP/FP occurrences would require a larger schema change.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000004"
down_revision: str | Sequence[str] | None = "20251220000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recreate occurrence_credits view to read from normalized grading_decisions."""
    # Drop dependent views first (CASCADE)
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")

    # Recreate occurrence_credits reading from grading_decisions
    op.execute(
        """
        CREATE VIEW occurrence_credits AS
        -- Successful grader runs: Read from normalized grading_decisions table
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
            -- Aggregate input issue IDs into JSON array (matched_by)
            jsonb_agg(gd.input_issue_id ORDER BY gd.input_issue_id) AS matched_by_json,
            -- Pick first non-null rationale (they should all be similar for same occurrence)
            MAX(gd.rationale) AS grader_rationale
        FROM grader_runs gr
        JOIN critic_runs cr ON gr.critic_run_id = cr.id
        JOIN snapshots s ON gr.snapshot_slug = s.slug
        JOIN examples ex ON cr.snapshot_slug = ex.snapshot_slug AND cr.scope_hash = ex.scope_hash
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        JOIN grading_decisions gd ON gr.id = gd.grader_run_id
        WHERE gd.target_tp_id IS NOT NULL  -- Only TP matches (not FPs, not unmatched)
        GROUP BY gr.id, gr.transcript_id, gr.created_at, gr.snapshot_slug, s.split,
                 ex.scope_hash, ex.scope, cr.id, cr.transcript_id, cr.prompt_sha256,
                 p.prompt_text, p.prompt_optimization_run_id, cr.model, gr.model,
                 gd.target_tp_id, gd.target_tp_occurrence_id

        UNION ALL

        -- Failed critic runs (no grader run): Read from true_positives.occurrences JSONB
        -- (Normalizing TP occurrences is a larger schema change - defer for now)
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
            'Critic failed: ' || (cr.output->>'tag') AS grader_rationale
        FROM critic_runs cr
        JOIN snapshots s ON cr.snapshot_slug = s.slug
        JOIN examples ex ON cr.snapshot_slug = ex.snapshot_slug AND cr.scope_hash = ex.scope_hash
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        JOIN true_positives tp ON tp.snapshot_slug = ex.snapshot_slug
        CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) AS occ_data
        LEFT JOIN grader_runs gr_exists ON gr_exists.critic_run_id = cr.id
        WHERE (cr.output->>'tag') IN ('max_turns_exceeded', 'context_length_exceeded')
          AND gr_exists.id IS NULL
          AND (
              -- All files scope: all occurrences are relevant
              (ex.scope->>'kind') = 'entire_snapshot'
              OR
              -- Explicit files scope: only occurrences catchable from these files
              EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(occ_data.value->'expect_caught_from') AS trigger_set
                  WHERE (
                      SELECT bool_and(file_elem IN (SELECT jsonb_array_elements_text(ex.scope->'files')))
                      FROM jsonb_array_elements_text(trigger_set) AS file_elem
                  )
              )
          )
        """
    )

    # Recreate dependent view: occurrence_run_credits
    # Join back to critic_runs to check actual status instead of pattern matching on synthetic rationale
    op.execute(
        """
        CREATE VIEW occurrence_run_credits AS
        SELECT
            oc.split,
            oc.snapshot_slug,
            oc.scope_hash,
            oc.scope_kind,
            oc.tp_id,
            oc.occurrence_id,
            oc.critic_run_id,
            oc.critic_model,
            oc.grader_model,
            oc.prompt_sha256,
            AVG(oc.found_credit) AS avg_credit,
            -- Check actual critic_run status instead of pattern matching on rationale
            bool_or(oc.grader_run_id IS NULL AND cr.status = 'max_turns_exceeded') AS is_max_turns_failure,
            bool_or(oc.grader_run_id IS NULL AND cr.status = 'context_length_exceeded') AS is_context_failure
        FROM occurrence_credits oc
        JOIN critic_runs cr ON oc.critic_run_id = cr.id
        GROUP BY oc.split, oc.snapshot_slug, oc.scope_hash, oc.scope_kind, oc.tp_id, oc.occurrence_id,
                 oc.critic_run_id, oc.critic_model, oc.grader_model, oc.prompt_sha256
        """
    )

    # Recreate dependent view: occurrence_statistics (aggregates from occurrence_run_credits)
    op.execute(
        """
        CREATE VIEW occurrence_statistics AS
        SELECT
            split,
            tp_id,
            occurrence_id,
            critic_model,
            grader_model,
            AVG(avg_credit) AS mean_credit,
            STDDEV(avg_credit) AS stddev_credit,
            MIN(avg_credit) AS min_credit,
            MAX(avg_credit) AS max_credit,
            COUNT(*) AS n_critic_runs,
            COUNT(DISTINCT prompt_sha256) AS n_prompts,
            SUM(CASE WHEN avg_credit = 1.0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS full_catch_rate
        FROM occurrence_run_credits
        GROUP BY split, tp_id, occurrence_id, critic_model, grader_model
        """
    )


def downgrade() -> None:
    """Restore occurrence_credits view to read from JSONB."""
    # Drop dependent views first
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")

    # Restore original occurrence_credits reading from JSONB
    op.execute(
        """
        CREATE VIEW occurrence_credits AS
        -- Successful grader runs: Read from JSONB gr.output
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
            occ_result.value->>'tp_id' AS tp_id,
            occ_result.value->>'occurrence_id' AS occurrence_id,
            (occ_result.value->>'found_credit')::float AS found_credit,
            occ_result.value->'matched_by' AS matched_by_json,
            occ_result.value->>'rationale' AS grader_rationale
        FROM grader_runs gr
        JOIN critic_runs cr ON gr.critic_run_id = cr.id
        JOIN snapshots s ON gr.snapshot_slug = s.slug
        JOIN examples ex ON cr.snapshot_slug = ex.snapshot_slug AND cr.scope_hash = ex.scope_hash
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        CROSS JOIN LATERAL jsonb_array_elements(gr.output->'occurrence_results') AS occ_result
        WHERE (gr.output->>'tag') = 'success'

        UNION ALL

        -- Failed critic runs (no grader run)
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
            'Critic failed: ' || (cr.output->>'tag') AS grader_rationale
        FROM critic_runs cr
        JOIN snapshots s ON cr.snapshot_slug = s.slug
        JOIN examples ex ON cr.snapshot_slug = ex.snapshot_slug AND cr.scope_hash = ex.scope_hash
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        JOIN true_positives tp ON tp.snapshot_slug = ex.snapshot_slug
        CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) AS occ_data
        LEFT JOIN grader_runs gr_exists ON gr_exists.critic_run_id = cr.id
        WHERE (cr.output->>'tag') IN ('max_turns_exceeded', 'context_length_exceeded')
          AND gr_exists.id IS NULL
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
        """
    )

    # Restore dependent views (with improved status checking)
    op.execute(
        """
        CREATE VIEW occurrence_run_credits AS
        SELECT
            oc.split,
            oc.snapshot_slug,
            oc.scope_hash,
            oc.scope_kind,
            oc.tp_id,
            oc.occurrence_id,
            oc.critic_run_id,
            oc.critic_model,
            oc.grader_model,
            oc.prompt_sha256,
            AVG(oc.found_credit) AS avg_credit,
            -- Check actual critic_run status (improvement from original LIKE pattern matching)
            bool_or(oc.grader_run_id IS NULL AND cr.status = 'max_turns_exceeded') AS is_max_turns_failure,
            bool_or(oc.grader_run_id IS NULL AND cr.status = 'context_length_exceeded') AS is_context_failure
        FROM occurrence_credits oc
        JOIN critic_runs cr ON oc.critic_run_id = cr.id
        GROUP BY oc.split, oc.snapshot_slug, oc.scope_hash, oc.scope_kind, oc.tp_id, oc.occurrence_id,
                 oc.critic_run_id, oc.critic_model, oc.grader_model, oc.prompt_sha256
        """
    )

    op.execute(
        """
        CREATE VIEW occurrence_statistics AS
        SELECT
            split,
            tp_id,
            occurrence_id,
            critic_model,
            grader_model,
            AVG(avg_credit) AS mean_credit,
            STDDEV(avg_credit) AS stddev_credit,
            MIN(avg_credit) AS min_credit,
            MAX(avg_credit) AS max_credit,
            COUNT(*) AS n_critic_runs,
            COUNT(DISTINCT prompt_sha256) AS n_prompts,
            SUM(CASE WHEN avg_credit = 1.0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS full_catch_rate
        FROM occurrence_run_credits
        GROUP BY split, tp_id, occurrence_id, critic_model, grader_model
        """
    )
