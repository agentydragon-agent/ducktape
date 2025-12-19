"""Add RLS policy for grader agents to read their own grader_run.

Revision ID: 20251222000002
Revises: 20251222000001
Create Date: 2025-12-22

The grader_runs table has RLS enabled, but the existing policies only cover:
- admin_full_access_grader_runs (admins)
- clustering_user_grader_runs_policy (clustering agents)
- prompt_optimizer_grader_runs (prompt optimizer agents)
- improvement_grader_runs_policy (improvement agents)

This breaks the grader agent's data access because policies like
`reported_issues_grader_read` use subqueries that depend on reading
grader_runs (e.g., `SELECT critic_run_id FROM grader_runs WHERE id = current_grader_run_id()`).

Without a policy allowing grader agents to read their own run, those
subqueries return 0 rows and graders can't see the data they need.

This migration adds the missing policy for grader agents.
"""

from alembic import op

revision = "20251222000002"
down_revision = "20251222000001"
branch_labels = None
depends_on = None


def upgrade():
    # Add policy for grader agents to read their own grader_run
    # This is required for other policies (like reported_issues_grader_read)
    # that use subqueries on grader_runs
    op.execute("""
        CREATE POLICY grader_runs_grader_self_read ON grader_runs
        FOR SELECT TO grader_agent_template
        USING (id = current_grader_run_id())
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS grader_runs_grader_self_read ON grader_runs")
