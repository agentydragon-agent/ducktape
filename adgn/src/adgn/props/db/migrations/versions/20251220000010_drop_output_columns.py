"""Drop output JSONB columns from critic_runs and grader_runs.

Revision ID: 20251220000010
Revises: 20251220000009
Create Date: 2025-12-20

All status information now lives in the status enum column.
All semantic data lives in normalized tables (reported_issues, grading_decisions).
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251220000010"
down_revision = "20251220000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop output columns - status is in enum column, data in normalized tables."""
    # First drop views that depend on critic_runs.output
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")

    # Drop critic_runs.output
    op.drop_column("critic_runs", "output")

    # Drop grader_runs.output
    op.drop_column("grader_runs", "output")

    # Recreate occurrence_credits view without output column reference
    # (use cr.status instead of cr.output->>'tag')
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
            jsonb_agg(gd.input_issue_id ORDER BY gd.input_issue_id) AS matched_by_json,
            MAX(gd.rationale) AS grader_rationale
        FROM grader_runs gr
        JOIN critic_runs cr ON gr.critic_run_id = cr.id
        JOIN snapshots s ON gr.snapshot_slug = s.slug
        JOIN examples ex ON cr.snapshot_slug = ex.snapshot_slug AND cr.scope_hash = ex.scope_hash
        JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
        JOIN grading_decisions gd ON gr.id = gd.grader_run_id
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
              occ_data.value->'files' ?| ARRAY(SELECT jsonb_array_elements_text(ex.scope->'files'))
              OR (ex.scope->>'kind') = 'AllFilesScope'
          )
    """
    )

    # Recreate dependent views
    op.execute(
        """
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
    """
    )

    op.execute(
        """
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
    """
    )


def downgrade() -> None:
    """Re-add output columns (data will be lost)."""
    # Re-add critic_runs.output (nullable)
    op.execute("""
        ALTER TABLE critic_runs
        ADD COLUMN output JSONB
    """)

    # Re-add grader_runs.output (nullable)
    op.execute("""
        ALTER TABLE grader_runs
        ADD COLUMN output JSONB
    """)
