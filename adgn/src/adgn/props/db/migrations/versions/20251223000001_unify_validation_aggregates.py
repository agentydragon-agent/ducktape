"""Unify get_validation_run_aggregates() to filter by target_metric.

Adds scope_kind and scope_hash to output, filters based on current user's
prompt optimizer target_metric:
- whole-repo: only entire_snapshot rows
- targeted: both entire_snapshot and explicit_file rows

Revision ID: 20251223000001
Revises: 20251223000000
Create Date: 2025-12-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251223000001"
down_revision: str | Sequence[str] | None = "20251223000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recreate get_validation_run_aggregates() with scope filtering."""
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    op.execute("""
        CREATE FUNCTION get_validation_run_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            prompt_sha256 text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status critic_run_status_enum,
            scope_kind scope_kind_enum,
            scope_hash text,
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
                cr.status,
                oc.scope_kind,
                oc.scope_hash,
                oc.tp_id,
                oc.occurrence_id,
                AVG(oc.found_credit) as avg_credit
            FROM occurrence_credits oc
            JOIN snapshots s ON oc.snapshot_slug = s.slug
            JOIN critic_runs cr ON oc.critic_run_id = cr.id
            WHERE s.split = 'valid'::split_enum
              AND (
                -- whole-repo mode: only entire_snapshot
                (current_prompt_optimizer_target_metric() = 'whole-repo'
                 AND oc.scope_kind = 'entire_snapshot')
                OR
                -- targeted mode: both scope kinds
                (current_prompt_optimizer_target_metric() = 'targeted')
                OR
                -- no prompt optimizer context: default to entire_snapshot only
                (current_prompt_optimizer_target_metric() IS NULL
                 AND oc.scope_kind = 'entire_snapshot')
              )
            GROUP BY oc.snapshot_slug, oc.prompt_sha256, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, cr.status, oc.scope_kind,
                     oc.scope_hash, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            prompt_sha256,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            status,
            scope_kind,
            scope_hash,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id, status, scope_kind, scope_hash
          ORDER BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id, scope_kind, scope_hash
        $$;
    """)

    op.execute("""
        COMMENT ON FUNCTION get_validation_run_aggregates() IS
        'Validation metrics filtered by prompt optimizer target_metric.
        Returns per-run recall for VALID split, grouped by scope.
        - whole-repo mode: only entire_snapshot scope_kind
        - targeted mode: both entire_snapshot and explicit_file scope_kinds
        - no context: defaults to entire_snapshot only
        SECURITY DEFINER bypasses RLS to access validation data.'
    """)


def downgrade() -> None:
    """Restore previous get_validation_run_aggregates() without scope filtering."""
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    op.execute("""
        CREATE FUNCTION get_validation_run_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            prompt_sha256 text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status critic_run_status_enum,
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
                cr.status,
                oc.tp_id,
                oc.occurrence_id,
                AVG(oc.found_credit) as avg_credit
            FROM occurrence_credits oc
            JOIN snapshots s ON oc.snapshot_slug = s.slug
            JOIN critic_runs cr ON oc.critic_run_id = cr.id
            WHERE s.split = 'valid'::split_enum
              AND oc.scope_kind = 'entire_snapshot'
            GROUP BY oc.snapshot_slug, oc.prompt_sha256, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, cr.status, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            prompt_sha256,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            status,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id, status
          ORDER BY snapshot_slug, prompt_sha256, critic_model, grader_model,
                   critic_run_id, grader_run_id
        $$;
    """)

    op.execute("""
        COMMENT ON FUNCTION get_validation_run_aggregates() IS
        'Black-box validation metrics for whole-repo mode.
        Returns per-run recall for VALID split, entire_snapshot scope_kind only.
        Includes critic_run status for proper outcome counting.
        Used by prompt optimizer in whole-repo validation mode.'
    """)
