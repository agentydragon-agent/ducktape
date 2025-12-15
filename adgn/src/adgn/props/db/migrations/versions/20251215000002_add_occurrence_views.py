"""add occurrence views for cross-run metrics aggregation

Revision ID: 20251215000002
Revises: 20251215000001
Create Date: 2025-12-15 00:00:02.000000

"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "20251215000002"
down_revision = "20251215000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create 4 layered views for occurrence-level metrics aggregation."""

    # View 1: occurrence_credits (source view - detailed)
    op.execute(
        text(
            """
            CREATE VIEW occurrence_credits AS
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
                (cr.files_hash = ex.files_hash OR (ex.is_whole_snapshot AND cr.files_hash IS NULL))
            )
            JOIN prompts p ON cr.prompt_sha256 = p.prompt_sha256
            CROSS JOIN LATERAL jsonb_array_elements(gr.output->'occurrence_results') AS occ_result
            WHERE gr.output->>'tag' = 'success';
            """
        )
    )

    # View 2: aggregated_recall_by_prompt (aggregated by prompt + models)
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

    # View 3: aggregated_recall_by_example (aggregated by example + models)
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

    # View 4: occurrence_statistics (statistics per occurrence)
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
    """Drop views in reverse dependency order."""
    # Views 2, 3, 4 depend on view 1, so drop them first
    op.execute(text("DROP VIEW IF EXISTS occurrence_statistics CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS occurrence_credits CASCADE;"))
