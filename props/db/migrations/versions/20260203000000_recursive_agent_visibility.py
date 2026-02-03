"""Make agent_runs visibility recursive using is_agent_ancestor.

Revision ID: 20260203000000
Revises: 20260129000000
Create Date: 2026-02-03
"""

from alembic import op

revision = "20260203000000"
down_revision = "20260129000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old direct-children-only policy
    op.execute("DROP POLICY IF EXISTS agent_runs_select_children ON agent_runs")

    # Create new recursive policy using is_agent_ancestor
    # is_agent_ancestor(ancestor_id, descendant_id) returns true if ancestor_id
    # is in the parent chain of descendant_id (includes self)
    op.execute("""
        CREATE POLICY agent_runs_select_descendants ON agent_runs FOR SELECT USING (
            is_agent_ancestor(current_agent_run_id(), agent_run_id)
        )
    """)


def downgrade() -> None:
    # Drop the recursive policy
    op.execute("DROP POLICY IF EXISTS agent_runs_select_descendants ON agent_runs")

    # Restore the direct-children-only policy
    op.execute(
        "CREATE POLICY agent_runs_select_children ON agent_runs FOR SELECT USING (parent_agent_run_id = current_agent_run_id())"
    )
