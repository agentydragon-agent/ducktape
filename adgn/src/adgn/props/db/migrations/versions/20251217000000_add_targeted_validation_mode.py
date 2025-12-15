"""Add targeted validation mode support for prompt optimizer

Revision ID: 20251217000000
Revises: 20251215000010
Create Date: 2025-12-17

Changes:
- Add current_prompt_optimizer_target_metric() function (queries prompt_optimization_runs.config)
- Enhance aggregated_recall_by_prompt view to include stats (n_examples, n_runs, ucb, lcb)
- Update examples RLS policy to allow VALID access in targeted mode
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20251217000000"
down_revision: str | Sequence[str] | None = "20251215000010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add targeted validation mode support."""

    # 1. Create function to query target metric from prompt_optimization_runs table
    op.execute(
        text(
            """
        CREATE OR REPLACE FUNCTION current_prompt_optimizer_target_metric()
        RETURNS TEXT AS $$
        DECLARE
            run_id UUID;
        BEGIN
            -- Get run_id from username via existing function
            run_id := current_prompt_optimizer_run_id();

            IF run_id IS NULL THEN
                RETURN NULL;
            END IF;

            -- Query config from prompt_optimization_runs table
            RETURN (
                SELECT config->>'target_metric'
                FROM prompt_optimization_runs
                WHERE id = run_id
            );
        END;
        $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
        """
        )
    )

    op.execute(
        text(
            """
        COMMENT ON FUNCTION current_prompt_optimizer_target_metric() IS
        'Returns target_metric from prompt_optimization_runs.config for current user.
        Returns NULL if not a prompt optimizer user or run not found.
        Used by RLS policies to enforce mode-specific access rules.';
        """
        )
    )

    # 2. Drop and recreate aggregated_recall_by_prompt with stats columns
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))

    op.execute(
        text(
            """
            CREATE VIEW aggregated_recall_by_prompt AS
            WITH per_run_recalls AS (
                -- Compute recall per critic run
                SELECT
                    split,
                    prompt_sha256,
                    critic_model,
                    is_whole_snapshot,
                    snapshot_slug,
                    files_hash,
                    critic_run_id,
                    SUM(avg_credit) as total_credit,
                    COUNT(*) as n_occurrences,
                    SUM(avg_credit) / NULLIF(COUNT(*), 0) as recall,
                    BOOL_OR(is_max_turns_failure) as is_max_turns_failure,
                    BOOL_OR(is_context_failure) as is_context_failure
                FROM occurrence_run_credits
                GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot,
                         snapshot_slug, files_hash, critic_run_id
            )
            SELECT
                split,
                prompt_sha256,
                critic_model,
                is_whole_snapshot,
                -- Existing aggregate columns
                SUM(total_credit) as total_credit,
                SUM(n_occurrences) as n_occurrences,
                AVG(recall) as recall,
                COUNT(DISTINCT snapshot_slug) as n_snapshots,
                -- New stats columns
                COUNT(DISTINCT files_hash) as n_examples,
                COUNT(DISTINCT critic_run_id) as n_runs,
                STDDEV(recall) as recall_stddev,
                AVG(recall) + COALESCE(STDDEV(recall) / SQRT(COUNT(DISTINCT critic_run_id)), 0) as ucb,
                AVG(recall) - COALESCE(STDDEV(recall) / SQRT(COUNT(DISTINCT critic_run_id)), 0) as lcb,
                -- Existing failure columns
                COUNT(DISTINCT CASE WHEN is_max_turns_failure THEN critic_run_id END) as n_max_turns_exceeded,
                COUNT(DISTINCT CASE WHEN is_context_failure THEN critic_run_id END) as n_context_length_exceeded
            FROM per_run_recalls
            GROUP BY split, prompt_sha256, critic_model, is_whole_snapshot;
            """
        )
    )

    op.execute(
        text(
            """
        COMMENT ON VIEW aggregated_recall_by_prompt IS
        'Aggregates recall metrics by prompt across all examples and runs.
        Includes sample size (n_examples, n_runs) and confidence bounds (ucb, lcb) for variance awareness.
        Per-run recall is computed first, then aggregated (stddev is stddev of per-run recalls).';
        """
        )
    )

    # 3. Update RLS policy on examples table for targeted mode
    op.execute(text("DROP POLICY IF EXISTS prompt_optimizer_examples ON examples"))

    op.execute(
        text(
            """
        CREATE POLICY prompt_optimizer_examples ON examples
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND (
                -- TRAIN: always accessible
                snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train'::split_enum)
                OR (
                    -- VALID: only in targeted mode
                    current_prompt_optimizer_target_metric() = 'targeted'
                    AND snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'valid'::split_enum)
                )
            )
        )
        """
        )
    )

    op.execute(
        text(
            """
        COMMENT ON POLICY prompt_optimizer_examples ON examples IS
        'Prompt optimizer access to examples table:
        - TRAIN split: always accessible (both whole-repo and targeted modes)
        - VALID split: only accessible in targeted mode (filenames only - no ground truth)
        - TEST split: never accessible (off-limits)';
        """
        )
    )

    # Note: Permissions (EXECUTE on new function, SELECT on enhanced view) are granted automatically
    # by PromptOptimizerUserManager.grant_permissions() when temporary user is created


def downgrade() -> None:
    """Remove targeted validation mode support."""

    # 1. Restore RLS policy to TRAIN-only
    op.execute(text("DROP POLICY IF EXISTS prompt_optimizer_examples ON examples"))

    op.execute(
        text(
            """
        CREATE POLICY prompt_optimizer_examples ON examples
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train'::split_enum)
        )
        """
        )
    )

    # 2. Restore aggregated_recall_by_prompt view without stats columns
    op.execute(text("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE;"))

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

    # 3. Drop target metric function
    op.execute(text("DROP FUNCTION IF EXISTS current_prompt_optimizer_target_metric()"))
