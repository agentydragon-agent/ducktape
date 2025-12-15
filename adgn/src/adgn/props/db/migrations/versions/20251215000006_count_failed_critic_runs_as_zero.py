"""count failed critic runs as zero-recall in occurrence views

Revision ID: 20251215000006
Revises: 20251215000005
Create Date: 2025-12-15 00:00:06.000000

Updates occurrence_credits view to include failed critic runs (max_turns_exceeded,
context_length_exceeded) with zero credit for all catchable occurrences.

Catchability is computed in SQL from expect_caught_from JSONB data:
- Whole-snapshot examples: all occurrences catchable
- File-set examples: occurrence catchable if ANY trigger_set is subset of example.files
"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "20251215000006"
down_revision = "20251215000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Update occurrence_credits view to count failures as zero."""

    # Drop dependent views first
    op.execute(text("DROP VIEW IF EXISTS occurrence_statistics CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS occurrence_credits CASCADE;"))

    # Recreate occurrence_credits with UNION to include failures
    op.execute(
        text(
            """
            CREATE VIEW occurrence_credits AS
            -- Successful runs (existing logic)
            SELECT
                -- Run identification
                gr.id as grader_run_id,
                gr.transcript_id as grader_transcript_id,
                gr.created_at as graded_at,

                -- Snapshot/Example context
                gr.snapshot_slug,
                s.split,
                ex.files_hash,
                ex.is_whole_snapshot,
                ex.files as reviewed_files,

                -- Critique provenance
                gr.critique_id,
                cr.id as critic_run_id,
                cr.transcript_id as critic_transcript_id,
                cr.prompt_sha256,
                p.prompt_text,
                p.prompt_optimization_run_id,

                -- Models
                cr.model as critic_model,
                gr.model as grader_model,

                -- Occurrence details (from JSONB)
                (occ_result->>'tp_id') as tp_id,
                (occ_result->>'occurrence_id') as occurrence_id,
                (occ_result->>'found_credit')::float as found_credit,
                (occ_result->'matched_by') as matched_by_json,
                (occ_result->>'rationale') as grader_rationale

            FROM grader_runs gr
            JOIN critiques c ON gr.critique_id = c.id
            JOIN critic_runs cr ON c.id = cr.critique_id
            JOIN snapshots s ON gr.snapshot_slug = s.slug
            JOIN examples ex ON (
                cr.snapshot_slug = ex.snapshot_slug AND
                (cr.files_hash = ex.files_hash OR ex.is_whole_snapshot = TRUE)
            )
            JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
            CROSS JOIN LATERAL jsonb_array_elements(gr.output->'occurrence_results') AS occ_result
            WHERE gr.output->>'tag' = 'success'

            UNION ALL

            -- Failed critic runs (max_turns_exceeded, context_length_exceeded)
            -- Generate zero-credit rows for all catchable occurrences
            SELECT
                -- Run identification (no grader run for failures)
                NULL::uuid as grader_run_id,
                NULL::uuid as grader_transcript_id,
                cr.created_at as graded_at,

                -- Snapshot/Example context
                cr.snapshot_slug,
                s.split,
                ex.files_hash,
                ex.is_whole_snapshot,
                ex.files as reviewed_files,

                -- Critique provenance (no critique for failures)
                NULL::uuid as critique_id,
                cr.id as critic_run_id,
                cr.transcript_id as critic_transcript_id,
                cr.prompt_sha256,
                p.prompt_text,
                p.prompt_optimization_run_id,

                -- Models
                cr.model as critic_model,
                NULL::text as grader_model,

                -- Occurrence details (zero credit for catchable occurrences)
                tp.tp_id,
                (occ_data->>'occurrence_id') as occurrence_id,
                0.0::float as found_credit,
                NULL::jsonb as matched_by_json,
                'Critic failed: ' || (cr.output->>'tag') as grader_rationale

            FROM critic_runs cr
            JOIN snapshots s ON cr.snapshot_slug = s.slug
            JOIN examples ex ON (
                cr.snapshot_slug = ex.snapshot_slug AND
                (cr.files_hash = ex.files_hash OR ex.is_whole_snapshot = TRUE)
            )
            JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
            JOIN true_positives tp ON tp.snapshot_slug = ex.snapshot_slug
            CROSS JOIN LATERAL jsonb_array_elements(tp.occurrences) AS occ_data
            WHERE cr.output->>'tag' IN ('max_turns_exceeded', 'context_length_exceeded')
              AND cr.critique_id IS NULL
              AND (
                -- Catchability check (computed from expect_caught_from)
                ex.is_whole_snapshot = TRUE
                OR EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(occ_data->'expect_caught_from') AS trigger_set
                  WHERE (
                    -- All files in this trigger_set must be in ex.files
                    SELECT bool_and(
                      file_elem::text = ANY(
                        SELECT jsonb_array_elements_text(ex.files)
                      )
                    )
                    FROM jsonb_array_elements_text(trigger_set) AS file_elem
                  )
                )
              )
            """
        )
    )

    # Recreate dependent views (unchanged from previous migration)
    op.execute(
        text(
            """
            CREATE VIEW aggregated_recall_by_prompt AS
            WITH occurrence_avg_credits AS (
                SELECT
                    split,
                    prompt_sha256,
                    critic_model,
                    grader_model,
                    is_whole_snapshot,
                    snapshot_slug,
                    files_hash,
                    tp_id,
                    occurrence_id,
                    AVG(found_credit) as avg_credit
                FROM occurrence_credits
                GROUP BY split, prompt_sha256, critic_model, grader_model, is_whole_snapshot,
                         snapshot_slug, files_hash, tp_id, occurrence_id
            )
            SELECT
                split,
                prompt_sha256,
                critic_model,
                grader_model,
                is_whole_snapshot,
                SUM(avg_credit) as total_credit,
                COUNT(*) as n_occurrences,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) as recall,
                COUNT(DISTINCT snapshot_slug) as n_snapshots,
                COUNT(DISTINCT files_hash) as n_examples
            FROM occurrence_avg_credits
            GROUP BY split, prompt_sha256, critic_model, grader_model, is_whole_snapshot;
            """
        )
    )

    op.execute(
        text(
            """
            CREATE VIEW aggregated_recall_by_example AS
            WITH occurrence_avg_credits AS (
                SELECT
                    split,
                    snapshot_slug,
                    files_hash,
                    critic_model,
                    grader_model,
                    tp_id,
                    occurrence_id,
                    AVG(found_credit) as avg_credit
                FROM occurrence_credits
                GROUP BY split, snapshot_slug, files_hash, critic_model, grader_model,
                         tp_id, occurrence_id
            )
            SELECT
                split,
                snapshot_slug,
                files_hash,
                critic_model,
                grader_model,
                SUM(avg_credit) as total_credit,
                COUNT(*) as n_occurrences,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) as recall
            FROM occurrence_avg_credits
            GROUP BY split, snapshot_slug, files_hash, critic_model, grader_model;
            """
        )
    )

    op.execute(
        text(
            """
            CREATE VIEW occurrence_statistics AS
            SELECT
                split,
                tp_id,
                occurrence_id,
                critic_model,
                grader_model,
                AVG(found_credit) as mean_credit,
                STDDEV(found_credit) as stddev_credit,
                MIN(found_credit) as min_credit,
                MAX(found_credit) as max_credit,
                COUNT(*) as n_runs,
                COUNT(DISTINCT prompt_sha256) as n_prompts,
                SUM(CASE WHEN found_credit = 1.0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) as full_catch_rate
            FROM occurrence_credits
            GROUP BY split, tp_id, occurrence_id, critic_model, grader_model;
            """
        )
    )


def downgrade() -> None:
    """Revert to views without failure tracking."""
    # Drop views
    op.execute(text("DROP VIEW IF EXISTS occurrence_statistics CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS occurrence_credits CASCADE;"))

    # Restore old occurrence_credits view (without failure tracking)
    # Would need to recreate from 20251215000002 - omitted for brevity
