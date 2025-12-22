"""Fix infinite recursion in current_agent_type() function.

The current_agent_type() function queries agent_runs table, but agent_runs
has an RLS policy that calls current_agent_type(), creating infinite recursion.

Fix: Make current_agent_type() use SECURITY DEFINER to bypass RLS when
querying agent_runs for the agent type.

Revision ID: 20251229000001
Revises: 20251229000000
Create Date: 2025-12-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251229000001"
down_revision: str | Sequence[str] | None = "20251229000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recreate current_agent_type() with SECURITY DEFINER to bypass RLS."""
    op.execute("DROP FUNCTION IF EXISTS current_agent_type() CASCADE")
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_type() RETURNS TEXT
        LANGUAGE plpgsql STABLE SECURITY DEFINER
        AS $$
        DECLARE
            agent_type TEXT;
            run_id UUID;
            run_id_text TEXT;
        BEGIN
            -- Extract run_id directly from session_user (not current_user)
            -- session_user is the original user that started the session,
            -- while current_user changes to the function owner in SECURITY DEFINER
            -- Username pattern: agent_{uuid}
            run_id_text := SUBSTRING(session_user FROM 'agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            run_id := run_id_text::UUID;

            -- Query agent_runs with SECURITY DEFINER to bypass RLS
            SELECT type_config->>'agent_type' INTO agent_type
            FROM agent_runs
            WHERE agent_run_id = run_id;

            RETURN agent_type;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_type() IS
            'Returns the agent_type from the current agent''s type_config. Uses SECURITY DEFINER to bypass RLS and session_user to get the original caller.';
    """)


def downgrade() -> None:
    """Restore current_agent_type() without SECURITY DEFINER."""
    op.execute("DROP FUNCTION IF EXISTS current_agent_type() CASCADE")
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_type() RETURNS TEXT
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            agent_type TEXT;
        BEGIN
            SELECT type_config->>'agent_type' INTO agent_type
            FROM agent_runs
            WHERE agent_run_id = current_agent_run_id();

            RETURN agent_type;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_type() IS
            'Returns the agent_type from the current agent''s type_config. Used for type-specific RLS policies.';
    """)
