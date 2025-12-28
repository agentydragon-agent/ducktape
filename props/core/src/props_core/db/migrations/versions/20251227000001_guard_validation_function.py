"""Add access guard to get_validation_full_snapshot_aggregates().

Only whole-repo mode agents (prompt_optimizer or improvement) can call this function.

Revision ID: 20251227000001
Revises: 20251227000000
Create Date: 2025-12-27
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251227000001"
down_revision = "20251227000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop and recreate with plpgsql + guard clause
    op.execute("DROP FUNCTION IF EXISTS get_validation_full_snapshot_aggregates()")

    op.execute("""
        CREATE FUNCTION get_validation_full_snapshot_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            critic_definition_id text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status agent_run_status_enum,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
        DECLARE
            config jsonb;
        BEGIN
            config := current_agent_type_config();

            -- Only allow whole-repo mode agents
            IF config IS NULL OR config->>'target_metric' != 'whole-repo' THEN
                RAISE EXCEPTION 'Access denied: get_validation_full_snapshot_aggregates() requires whole-repo target_metric';
            END IF;

            RETURN QUERY
            WITH occurrence_avg_credits AS (
                SELECT
                    oc.snapshot_slug,
                    oc.critic_definition_id,
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
                JOIN agent_runs cr ON oc.critic_run_id = cr.agent_run_id
                WHERE s.split = 'valid'::split_enum
                  AND oc.example_kind = 'whole_snapshot'
                  AND (cr.type_config->>'agent_type') = 'critic'
                GROUP BY oc.snapshot_slug, oc.critic_definition_id, oc.critic_model, oc.grader_model,
                         oc.critic_run_id, oc.grader_run_id, cr.status, oc.tp_id, oc.occurrence_id
            )
            SELECT
                occurrence_avg_credits.snapshot_slug,
                occurrence_avg_credits.critic_definition_id,
                occurrence_avg_credits.critic_model,
                occurrence_avg_credits.grader_model,
                occurrence_avg_credits.critic_run_id,
                occurrence_avg_credits.grader_run_id,
                occurrence_avg_credits.status,
                SUM(avg_credit) as total_credit,
                CAST(COUNT(*) AS integer) as n_occurrences
            FROM occurrence_avg_credits
            GROUP BY occurrence_avg_credits.snapshot_slug, occurrence_avg_credits.critic_definition_id,
                     occurrence_avg_credits.critic_model, occurrence_avg_credits.grader_model,
                     occurrence_avg_credits.critic_run_id, occurrence_avg_credits.grader_run_id,
                     occurrence_avg_credits.status
            ORDER BY occurrence_avg_credits.snapshot_slug, occurrence_avg_credits.critic_definition_id,
                     occurrence_avg_credits.critic_model, occurrence_avg_credits.grader_model,
                     occurrence_avg_credits.critic_run_id, occurrence_avg_credits.grader_run_id;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION get_validation_full_snapshot_aggregates() IS
        'Black-box validation metrics for whole-repo mode.
Returns per-run recall for VALID split, whole_snapshot example_kind only.
Includes critic_run status for proper outcome counting.
Requires caller to be a whole-repo mode agent (prompt_optimizer or improvement).'
    """)


def downgrade() -> None:
    # Restore original sql version without guard
    op.execute("DROP FUNCTION IF EXISTS get_validation_full_snapshot_aggregates()")

    op.execute("""
        CREATE FUNCTION get_validation_full_snapshot_aggregates()
        RETURNS TABLE(
            snapshot_slug text,
            critic_definition_id text,
            critic_model text,
            grader_model text,
            critic_run_id uuid,
            grader_run_id uuid,
            status agent_run_status_enum,
            total_credit double precision,
            n_occurrences integer
        )
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path TO 'public'
        AS $$
          WITH occurrence_avg_credits AS (
            SELECT
                oc.snapshot_slug,
                oc.critic_definition_id,
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
            JOIN agent_runs cr ON oc.critic_run_id = cr.agent_run_id
            WHERE s.split = 'valid'::split_enum
              AND oc.example_kind = 'whole_snapshot'
              AND (cr.type_config->>'agent_type') = 'critic'
            GROUP BY oc.snapshot_slug, oc.critic_definition_id, oc.critic_model, oc.grader_model,
                     oc.critic_run_id, oc.grader_run_id, cr.status, oc.tp_id, oc.occurrence_id
          )
          SELECT
            snapshot_slug,
            critic_definition_id,
            critic_model,
            grader_model,
            critic_run_id,
            grader_run_id,
            status,
            SUM(avg_credit) as total_credit,
            CAST(COUNT(*) AS integer) as n_occurrences
          FROM occurrence_avg_credits
          GROUP BY snapshot_slug, critic_definition_id, critic_model, grader_model,
                   critic_run_id, grader_run_id, status
          ORDER BY snapshot_slug, critic_definition_id, critic_model, grader_model,
                   critic_run_id, grader_run_id
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION get_validation_full_snapshot_aggregates() IS
        'Black-box validation metrics for whole-repo mode.
Returns per-run recall for VALID split, whole_snapshot example_kind only.
Includes critic_run status for proper outcome counting.
Used by prompt optimizer in whole-repo validation mode.'
    """)
