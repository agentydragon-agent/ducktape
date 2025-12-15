"""Add failure counts to aggregated views

Revision ID: 20251215000008
Revises: 20251215000007
Create Date: 2025-12-15 00:00:08

Adds columns to aggregated_recall_by_prompt tracking:
- n_critic_runs: Total number of critic runs (successful + failed)
- n_max_turns_exceeded: Count of runs that exceeded max turns
- n_context_length_exceeded: Count of runs that exceeded context length
"""

from alembic import op
from sqlalchemy import text

revision = "20251215000008"
down_revision = "20251215000007"


def upgrade() -> None:
    """Add failure tracking columns to aggregated_recall_by_prompt."""

    # Drop dependent views first
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))

    # Recreate aggregated_recall_by_prompt with failure tracking
    op.execute(
        text(
            """
            CREATE VIEW aggregated_recall_by_prompt AS
            WITH occurrence_run_avg_credits AS (
                SELECT
                    split,
                    prompt_sha256,
                    critic_model,
                    is_whole_snapshot,
                    snapshot_slug,
                    files_hash,
                    tp_id,
                    occurrence_id,
                    critic_run_id,
                    AVG(found_credit) as avg_credit,
                    BOOL_OR(grader_run_id IS NULL AND grader_rationale LIKE '%max_turns_exceeded%') as is_max_turns_failure,
                    BOOL_OR(grader_run_id IS NULL AND grader_rationale LIKE '%context_length_exceeded%') as is_context_failure
                FROM occurrence_credits
                GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot,
                         snapshot_slug, files_hash, tp_id, occurrence_id, critic_run_id
            )
            SELECT
                split,
                prompt_sha256,
                critic_model,
                is_whole_snapshot,
                SUM(avg_credit) as total_credit,
                COUNT(*) as n_occurrences,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) as recall,
                COUNT(DISTINCT snapshot_slug) as n_snapshots,
                COUNT(DISTINCT files_hash) as n_examples,
                COUNT(DISTINCT critic_run_id) as n_critic_runs,
                COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) as n_max_turns_exceeded,
                COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) as n_context_length_exceeded
            FROM occurrence_run_avg_credits
            GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot;
            """
        )
    )


def downgrade() -> None:
    """Restore view without failure tracking columns."""

    # Drop view with failure tracking
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))

    # Recreate old view (without failure tracking)
    op.execute(
        text(
            """
            CREATE VIEW aggregated_recall_by_prompt AS
            WITH occurrence_avg_credits AS (
                SELECT
                    split,
                    prompt_sha256,
                    critic_model,
                    is_whole_snapshot,
                    snapshot_slug,
                    files_hash,
                    tp_id,
                    occurrence_id,
                    AVG(found_credit) as avg_credit
                FROM occurrence_credits
                GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot,
                         snapshot_slug, files_hash, tp_id, occurrence_id
            )
            SELECT
                split,
                prompt_sha256,
                critic_model,
                is_whole_snapshot,
                SUM(avg_credit) as total_credit,
                COUNT(*) as n_occurrences,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) as recall,
                COUNT(DISTINCT snapshot_slug) as n_snapshots,
                COUNT(DISTINCT files_hash) as n_examples
            FROM occurrence_avg_credits
            GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot;
            """
        )
    )
