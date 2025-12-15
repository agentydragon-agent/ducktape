"""Add SECURITY DEFINER functions for validation access

Revision ID: 20251215000004
Revises: 20251215000003
Create Date: 2025-12-15 00:00:04
"""

from alembic import op
from sqlalchemy import text

revision = "20251215000004"
down_revision = "20251215000003"


def upgrade() -> None:
    """Create SECURITY DEFINER function for validation snapshot performance."""

    op.execute(
        text(
            """
        CREATE FUNCTION get_validation_snapshot_performance()
        RETURNS TABLE(
          snapshot_slug text,
          prompt_sha256 text,
          critic_model text,
          grader_model text,
          total_credit double precision,
          n_occurrences integer
        )
        SECURITY DEFINER
        SET search_path = public
        LANGUAGE SQL
        STABLE
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.prompt_sha256,
                oc.critic_model,
                oc.grader_model,
                oc.tp_id,
                oc.occurrence_id,
                AVG(oc.found_credit) as avg_credit
            FROM occurrence_credits oc
            JOIN snapshots s ON oc.snapshot_slug = s.slug
            WHERE s.split = 'valid'::split_enum
              AND oc.is_whole_snapshot = true
            GROUP BY oc.snapshot_slug, oc.prompt_sha256, oc.critic_model, oc.grader_model,
                     oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            prompt_sha256,
            critic_model,
            grader_model,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, prompt_sha256, critic_model, grader_model
        $$;
    """
        )
    )

    op.execute(
        text(
            """
        COMMENT ON FUNCTION get_validation_snapshot_performance() IS
        'Returns aggregated validation performance for all full-snapshot runs on VALID split.
        Accessible by prompt optimizer agents via SECURITY DEFINER privilege escalation.
        Individual prompt optimizer users receive EXECUTE permission via PromptOptimizerUserManager.
        Returns one row per (snapshot_slug, prompt_sha256, critic_model, grader_model) combination.
        Columns: snapshot_slug, prompt_sha256, critic_model, grader_model, total_credit (sum of found_credits), n_occurrences (count of occurrences).
        Agent can filter with WHERE clauses: WHERE prompt_sha256 = ''abc123...'' OR snapshot_slug = ''foo/bar''';
    """
        )
    )

    # Note: EXECUTE permission is granted to individual users by PromptOptimizerUserManager.grant_permissions()
    # No role-based grant needed here since users are created individually, not as role members


def downgrade() -> None:
    """Drop validation access functions."""
    op.execute(text("DROP FUNCTION IF EXISTS get_validation_snapshot_performance()"))
