"""Make current_agent_type() use current_agent_type_config().

Removes duplicate code by having current_agent_type() simply extract 'agent_type'
from the existing SECURITY DEFINER current_agent_type_config() function.

Uses CREATE OR REPLACE (no DROP CASCADE) to preserve dependent RLS policies.

Revision ID: 20251231000005
Revises: 20251231000004
Create Date: 2025-12-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251231000005"
down_revision: str | Sequence[str] | None = "20251231000004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Simplify current_agent_type() to use current_agent_type_config().

    Uses CREATE OR REPLACE instead of DROP CASCADE to preserve dependent RLS
    policies. The function signature (returns TEXT) remains the same.
    """
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_type() RETURNS TEXT
        LANGUAGE sql STABLE SECURITY DEFINER
        AS $$
            SELECT current_agent_type_config()->>'agent_type'
        $$;

        COMMENT ON FUNCTION current_agent_type() IS
            'Returns agent_type from current_agent_type_config(). SECURITY DEFINER for RLS policy use.';
    """)


def downgrade() -> None:
    """Restore standalone current_agent_type() implementation.

    Uses CREATE OR REPLACE to preserve dependent RLS policies.
    """
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_type() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            agent_type TEXT;
            run_id UUID;
            run_id_text TEXT;
        BEGIN
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;

            SELECT type_config->>'agent_type' INTO agent_type
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN agent_type;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_type() IS
            'Returns the agent_type from the current agent''s type_config. Uses SECURITY DEFINER to bypass RLS and session_user to get the original caller.';
    """)
