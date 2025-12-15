"""Drop agent_user role

Revision ID: 20251215000001
Revises: 20251215000000
Create Date: 2025-12-15

Removes the deprecated agent_user role after switchover to temporary users.
Safe to apply after all systems using agent_user have migrated to temporary users.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20251215000001"
down_revision: str | Sequence[str] | None = "20251215000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop agent_user role and its RLS policies."""
    # Check if agent_user role exists before attempting cleanup
    connection = op.get_bind()
    result = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'agent_user'"))
    agent_user_exists = result.scalar() is not None

    if not agent_user_exists:
        # Role doesn't exist (new schema), nothing to clean up
        return

    # Drop agent_user RLS policies (created in initial schema)
    op.execute("DROP POLICY IF EXISTS agent_user_snapshots ON snapshots")
    op.execute("DROP POLICY IF EXISTS agent_user_true_positives ON true_positives")
    op.execute("DROP POLICY IF EXISTS agent_user_false_positives ON false_positives")
    op.execute("DROP POLICY IF EXISTS agent_user_examples ON examples")

    # Revoke all grants from agent_user
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM agent_user")
    op.execute("REVOKE ALL PRIVILEGES ON SCHEMA public FROM agent_user")

    # Terminate any active connections (if any exist)
    op.execute("""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE usename = 'agent_user'
        AND pid <> pg_backend_pid()
    """)

    # Drop all objects owned by agent_user in the current database
    # This handles any default privileges, sequences, or other dependencies
    op.execute("REASSIGN OWNED BY agent_user TO postgres")
    op.execute("DROP OWNED BY agent_user")

    # Drop the role
    op.execute("DROP ROLE agent_user")


def downgrade() -> None:
    """Recreate agent_user role and policies.

    Note: This downgrade recreates the role structure but does NOT restore the original password.
    The password placeholder must be replaced with the actual password from vault if rollback is needed.
    """
    # Recreate role
    op.execute("""
        CREATE ROLE agent_user WITH
        LOGIN
        PASSWORD '<placeholder_password_replace_from_vault>'
        NOSUPERUSER
        INHERIT
        NOCREATEDB
        NOCREATEROLE
        NOREPLICATION
    """)

    # Grant permissions
    op.execute("GRANT USAGE ON SCHEMA public TO agent_user")
    op.execute("GRANT SELECT ON snapshots, true_positives, false_positives, examples TO agent_user")

    # Recreate RLS policies (TRAIN split only)
    op.execute("""
        CREATE POLICY agent_user_snapshots ON snapshots
        FOR SELECT TO agent_user
        USING (split = 'TRAIN')
    """)

    op.execute("""
        CREATE POLICY agent_user_true_positives ON true_positives
        FOR SELECT TO agent_user
        USING (snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'TRAIN'))
    """)

    op.execute("""
        CREATE POLICY agent_user_false_positives ON false_positives
        FOR SELECT TO agent_user
        USING (snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'TRAIN'))
    """)

    op.execute("""
        CREATE POLICY agent_user_examples ON examples
        FOR SELECT TO agent_user
        USING (snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'TRAIN'))
    """)
