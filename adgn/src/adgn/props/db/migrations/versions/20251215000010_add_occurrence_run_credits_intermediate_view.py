"""Add occurrence_run_credits intermediate view and fix weighting in all aggregated views

Revision ID: 20251215000010
Revises: 20251215000009
Create Date: 2025-12-15 00:00:10

Changes:
- Add occurrence_run_credits view: groups by (occurrence, critic_run) and averages across graders
- Refactor aggregated_recall_by_prompt to use occurrence_run_credits
- Refactor aggregated_recall_by_example to use occurrence_run_credits (fixes weighting, adds failure counts)
- Refactor occurrence_statistics to use occurrence_run_credits (fixes weighting, renames n_runs to n_critic_runs)

This eliminates duplication and ensures consistent weighting across all views.
"""

from alembic import op
from sqlalchemy import text

revision = "20251215000010"
down_revision = "20251215000009"


def upgrade() -> None:
    """Add intermediate view and refactor dependent views."""

    # Drop all dependent views first
    op.execute(text("DROP VIEW IF EXISTS occurrence_statistics CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))

    # Create intermediate view: one row per (occurrence, critic_run)
    # Averages found_credit across multiple grader runs for the same critic run
    op.execute(
        text(
            """
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
                AVG(found_credit) as avg_credit,
                BOOL_OR(grader_run_id IS NULL AND grader_rationale LIKE '%max_turns_exceeded%') as is_max_turns_failure,
                BOOL_OR(grader_run_id IS NULL AND grader_rationale LIKE '%context_length_exceeded%') as is_context_failure
            FROM occurrence_credits
            GROUP BY split, snapshot_slug, files_hash, is_whole_snapshot, tp_id, occurrence_id,
                     critic_run_id, critic_model, prompt_sha256;
            """
        )
    )

    # Recreate aggregated_recall_by_prompt using intermediate view
    op.execute(
        text(
            """
            CREATE VIEW aggregated_recall_by_prompt AS
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
            FROM occurrence_run_credits
            GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot;
            """
        )
    )

    # Recreate aggregated_recall_by_example using intermediate view (now with failure counts)
    op.execute(
        text(
            """
            CREATE VIEW aggregated_recall_by_example AS
            SELECT
                split,
                snapshot_slug,
                files_hash,
                critic_model,
                SUM(avg_credit) as total_credit,
                COUNT(*) as n_occurrences,
                SUM(avg_credit) / NULLIF(COUNT(*), 0) as recall,
                COUNT(DISTINCT critic_run_id) as n_critic_runs,
                COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) as n_max_turns_exceeded,
                COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) as n_context_length_exceeded
            FROM occurrence_run_credits
            GROUP BY split, snapshot_slug, files_hash, critic_model;
            """
        )
    )

    # Recreate occurrence_statistics using intermediate view (n_runs → n_critic_runs)
    op.execute(
        text(
            """
            CREATE VIEW occurrence_statistics AS
            SELECT
                split,
                tp_id,
                occurrence_id,
                critic_model,
                AVG(avg_credit) as mean_credit,
                STDDEV(avg_credit) as stddev_credit,
                MIN(avg_credit) as min_credit,
                MAX(avg_credit) as max_credit,
                COUNT(*) as n_critic_runs,
                COUNT(DISTINCT prompt_sha256) as n_prompts,
                SUM(CASE WHEN avg_credit = 1.0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) as full_catch_rate
            FROM occurrence_run_credits
            GROUP BY split, tp_id, occurrence_id, critic_model;
            """
        )
    )


def downgrade() -> None:
    """Restore views without intermediate view (with weighting bugs)."""

    # Drop all views
    op.execute(text("DROP VIEW IF EXISTS occurrence_statistics CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))
    op.execute(text("DROP VIEW IF EXISTS occurrence_run_credits CASCADE;"))

    # Restore aggregated_recall_by_prompt (without failure counts, with grader_model bug)
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

    # Restore aggregated_recall_by_example (with grader_model bug, no failure counts)
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

    # Restore occurrence_statistics (with grader_model bug)
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
