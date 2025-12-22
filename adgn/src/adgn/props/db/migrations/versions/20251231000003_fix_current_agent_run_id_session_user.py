"""Fix current_agent_run_id to use session_user instead of current_user.

Revision ID: 20251231000003
Revises: 20251231000002
Create Date: 2025-12-31

The current_agent_run_id() function uses current_user, but when called from
within a SECURITY DEFINER function (like current_agent_type()), current_user
changes to the function owner (postgres), not the original connecting user.

session_user always reflects the original connecting user, regardless of
SECURITY DEFINER context.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251231000003"
down_revision: str | Sequence[str] | None = "20251231000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace current_user with session_user in current_agent_run_id()."""
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_run_id() RETURNS uuid
        LANGUAGE SQL STABLE
        AS $$
            SELECT CASE
                WHEN session_user LIKE 'agent_%'
                THEN substring(session_user from 'agent_([0-9a-f-]+)')::uuid
                ELSE NULL
            END
        $$;

        COMMENT ON FUNCTION current_agent_run_id() IS
            'Extract agent_run_id from session username (NULL if not an agent). '
            'Uses session_user (not current_user) to work correctly when called '
            'from within SECURITY DEFINER functions.';
    """)


def downgrade() -> None:
    """Revert to current_user (original behavior)."""
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_run_id() RETURNS uuid
        LANGUAGE SQL STABLE
        AS $$
            SELECT CASE
                WHEN current_user LIKE 'agent_%'
                THEN substring(current_user from 'agent_([0-9a-f-]+)')::uuid
                ELSE NULL
            END
        $$;

        COMMENT ON FUNCTION current_agent_run_id() IS
            'Extract agent_run_id from session username (NULL if not an agent)';
    """)
