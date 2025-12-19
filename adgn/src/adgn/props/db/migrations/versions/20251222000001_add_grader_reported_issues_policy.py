"""Add RLS policies for agent data access.

Revision ID: 20251222000001
Revises: 20251222000000
Create Date: 2025-12-22

Critic agents need:
1. Read access to the example they're reviewing (examples table)

Graders need to read:
1. reported_issues for the critic_run they're grading
2. reported_issue_occurrences for the critic_run they're grading
3. true_positives for the snapshot they're grading
4. false_positives for the snapshot they're grading

The existing RLS policies only allow limited access for critic agents.
This migration adds policies that allow agents to read the data they need.
"""

from alembic import op

revision = "20251222000001"
down_revision = "20251222000000"
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # Critic Agent Policies
    # =========================================================================

    # Grant SELECT on examples table to critic template (if not already granted)
    op.execute("GRANT SELECT ON TABLE examples TO critic_agent_template")

    # Add policy for critic to read its own example (matching snapshot_slug and scope_hash)
    op.execute("""
        CREATE POLICY examples_critic_read ON examples
        FOR SELECT TO critic_agent_template
        USING (
            (snapshot_slug, scope_hash) IN (
                SELECT snapshot_slug, scope_hash FROM critic_runs
                WHERE id = current_critic_run_id()
            )
        )
    """)

    # =========================================================================
    # Grader Agent Policies
    # =========================================================================

    # Add policy for grader to read reported_issues for the critic_run being graded
    # The grader's grader_run.critic_run_id indicates which critic run they're grading
    op.execute("""
        CREATE POLICY reported_issues_grader_read ON reported_issues
        FOR SELECT TO grader_agent_template
        USING (
            critic_run_id IN (
                SELECT critic_run_id FROM grader_runs
                WHERE id = current_grader_run_id()
            )
        )
    """)

    # Also add policy for reported_issue_occurrences (same pattern)
    op.execute("""
        CREATE POLICY reported_issue_occurrences_grader_read ON reported_issue_occurrences
        FOR SELECT TO grader_agent_template
        USING (
            critic_run_id IN (
                SELECT critic_run_id FROM grader_runs
                WHERE id = current_grader_run_id()
            )
        )
    """)

    # Add policy for grader to read true_positives for the snapshot being graded
    op.execute("""
        CREATE POLICY true_positives_grader_read ON true_positives
        FOR SELECT TO grader_agent_template
        USING (
            snapshot_slug IN (
                SELECT snapshot_slug FROM grader_runs
                WHERE id = current_grader_run_id()
            )
        )
    """)

    # Add policy for grader to read false_positives for the snapshot being graded
    op.execute("""
        CREATE POLICY false_positives_grader_read ON false_positives
        FOR SELECT TO grader_agent_template
        USING (
            snapshot_slug IN (
                SELECT snapshot_slug FROM grader_runs
                WHERE id = current_grader_run_id()
            )
        )
    """)


def downgrade():
    # Critic policies
    op.execute("DROP POLICY IF EXISTS examples_critic_read ON examples")
    op.execute("REVOKE SELECT ON TABLE examples FROM critic_agent_template")

    # Grader policies
    op.execute("DROP POLICY IF EXISTS reported_issues_grader_read ON reported_issues")
    op.execute("DROP POLICY IF EXISTS reported_issue_occurrences_grader_read ON reported_issue_occurrences")
    op.execute("DROP POLICY IF EXISTS true_positives_grader_read ON true_positives")
    op.execute("DROP POLICY IF EXISTS false_positives_grader_read ON false_positives")
