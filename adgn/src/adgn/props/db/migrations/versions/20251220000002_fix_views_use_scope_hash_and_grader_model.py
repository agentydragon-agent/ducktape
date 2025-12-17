"""Add grader_model to aggregation views

Revision ID: 20251220000002
Revises: 20251220000001
Create Date: 2025-12-16 11:29:46.394872

Adds grader_model column to:
- occurrence_run_credits (SELECT and GROUP BY)
- aggregated_recall_by_example (SELECT and GROUP BY)
- aggregated_recall_by_prompt (SELECT and GROUP BY)
- occurrence_statistics (SELECT and GROUP BY)

This allows aggregating metrics separately by grader model.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251220000002"
down_revision: str | Sequence[str] | None = "20251220000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add grader_model to aggregation views."""
    # Drop views in reverse dependency order
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")

    # Recreate occurrence_run_credits with grader_model
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
            grader_model,
            prompt_sha256,
            AVG(found_credit) AS avg_credit,
            bool_or(grader_run_id IS NULL AND grader_rationale LIKE '%max_turns_exceeded%') AS is_max_turns_failure,
            bool_or(grader_run_id IS NULL AND grader_rationale LIKE '%context_length_exceeded%') AS is_context_failure
        FROM occurrence_credits
        GROUP BY split, snapshot_slug, scope_hash, scope_kind, tp_id, occurrence_id, critic_run_id, critic_model, grader_model, prompt_sha256
    """)

    # Recreate aggregated_recall_by_example with grader_model
    op.execute("""
        CREATE VIEW aggregated_recall_by_example AS
        SELECT
            split,
            snapshot_slug,
            scope_hash,
            critic_model,
            grader_model,
            SUM(avg_credit) AS total_credit,
            COUNT(*) AS n_occurrences,
            SUM(avg_credit) / NULLIF(COUNT(*), 0) AS recall,
            COUNT(DISTINCT critic_run_id) AS n_critic_runs,
            COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) AS n_max_turns_exceeded,
            COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) AS n_context_length_exceeded
        FROM occurrence_run_credits
        GROUP BY split, snapshot_slug, scope_hash, critic_model, grader_model
    """)

    # Recreate aggregated_recall_by_prompt with grader_model
    op.execute("""
        CREATE VIEW aggregated_recall_by_prompt AS
        WITH per_run_recalls AS (
            SELECT
                split,
                prompt_sha256,
                critic_model,
                grader_model,
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
            GROUP BY split, prompt_sha256, critic_model, grader_model, scope_kind, snapshot_slug, scope_hash, critic_run_id
        )
        SELECT
            split,
            prompt_sha256,
            critic_model,
            grader_model,
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
        GROUP BY split, prompt_sha256, critic_model, grader_model, scope_kind
    """)
    op.execute("""
        COMMENT ON VIEW aggregated_recall_by_prompt IS
        'Aggregates recall metrics by prompt across all examples and runs.
        Groups by scope_kind (discriminator from scope JSONB: entire_snapshot or specific_files) and grader_model.
        Includes sample size (n_examples, n_runs) and confidence bounds (ucb, lcb) for variance awareness.
        Per-run recall is computed first, then aggregated (stddev is stddev of per-run recalls).'
    """)

    # Recreate occurrence_statistics with grader_model
    op.execute("""
        CREATE VIEW occurrence_statistics AS
        SELECT
            split,
            tp_id,
            occurrence_id,
            critic_model,
            grader_model,
            AVG(avg_credit) AS mean_credit,
            stddev(avg_credit) AS stddev_credit,
            MIN(avg_credit) AS min_credit,
            MAX(avg_credit) AS max_credit,
            COUNT(*) AS n_critic_runs,
            COUNT(DISTINCT prompt_sha256) AS n_prompts,
            SUM(CASE WHEN avg_credit = 1.0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS full_catch_rate
        FROM occurrence_run_credits
        GROUP BY split, tp_id, occurrence_id, critic_model, grader_model
    """)


def downgrade() -> None:
    """Remove grader_model from aggregation views."""
    # Drop views in reverse dependency order
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")

    # Recreate occurrence_run_credits without grader_model
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

    # Recreate aggregated_recall_by_example without grader_model
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

    # Recreate aggregated_recall_by_prompt without grader_model
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

    # Recreate occurrence_statistics without grader_model
    op.execute("""
        CREATE VIEW occurrence_statistics AS
        SELECT
            split,
            tp_id,
            occurrence_id,
            critic_model,
            AVG(avg_credit) AS mean_credit,
            stddev(avg_credit) AS stddev_credit,
            MIN(avg_credit) AS min_credit,
            MAX(avg_credit) AS max_credit,
            COUNT(*) AS n_critic_runs,
            COUNT(DISTINCT prompt_sha256) AS n_prompts,
            SUM(CASE WHEN avg_credit = 1.0 THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS full_catch_rate
        FROM occurrence_run_credits
        GROUP BY split, tp_id, occurrence_id, critic_model
    """)
