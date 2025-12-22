"""Add UPDATE policies for reported_issues and reported_issue_occurrences.

The 20251224000000 migration added RLS policies for SELECT, INSERT, DELETE
but forgot UPDATE. This caused permission denied errors when critic agents
tried to update existing occurrences.

Revision ID: 20251225000000
Revises: 20251224000001
Create Date: 2025-12-19
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251225000000"
down_revision = "20251224000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add UPDATE policies for reported_issues and reported_issue_occurrences."""
    op.execute("""
        CREATE POLICY reported_issues_agent_update ON reported_issues
            FOR UPDATE
            USING (agent_run_id = current_agent_run_id())
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issue_occurrences_agent_update ON reported_issue_occurrences
            FOR UPDATE
            USING (agent_run_id = current_agent_run_id())
            WITH CHECK (agent_run_id = current_agent_run_id());
    """)


def downgrade() -> None:
    """Remove UPDATE policies."""
    op.execute("""
        DROP POLICY IF EXISTS reported_issues_agent_update ON reported_issues;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_update ON reported_issue_occurrences;
    """)
