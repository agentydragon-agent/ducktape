"""Fix RLS policies for grading_decisions and reported_issues.

Revision ID: 20251231000004
Revises: 20251231000003
Create Date: 2025-12-31

Fixes for tables with agent type-based policies:

1. Both grading_decisions and reported_issues INSERT/UPDATE/DELETE policies use
   inline subqueries to agent_runs which are subject to RLS, causing circular
   dependency. Solution: Use current_agent_type() which is SECURITY DEFINER.

2. The grading_decisions.agent_run_id column has no DEFAULT, so inserts fail.
   Solution: Add DEFAULT current_agent_run_id() so the column is auto-populated.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251231000004"
down_revision: str | Sequence[str] | None = "20251231000003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Update grading_decisions and reported_issues policies."""
    # Step 1: Add default for grading_decisions.agent_run_id column
    op.execute("""
        ALTER TABLE grading_decisions
        ALTER COLUMN agent_run_id SET DEFAULT current_agent_run_id();
    """)

    # Step 2: Update grading_decisions RLS policies to use current_agent_type()
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_agent_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_update ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_delete ON grading_decisions;

        -- INSERT: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY grading_decisions_agent_insert ON grading_decisions
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'grader'
            );

        -- UPDATE: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY grading_decisions_agent_update ON grading_decisions
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'grader'
            );

        -- DELETE: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY grading_decisions_agent_delete ON grading_decisions
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'grader'
            );
    """)

    # Step 3: Update reported_issues RLS policies to use current_agent_type()
    op.execute("""
        DROP POLICY IF EXISTS reported_issues_agent_insert ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_update ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_delete ON reported_issues;

        -- INSERT: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY reported_issues_agent_insert ON reported_issues
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );

        -- UPDATE: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY reported_issues_agent_update ON reported_issues
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );

        -- DELETE: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY reported_issues_agent_delete ON reported_issues
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );
    """)

    # Step 4: Update reported_issue_occurrences RLS policies to use current_agent_type()
    op.execute("""
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_insert ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_update ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_delete ON reported_issue_occurrences;

        -- INSERT: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY reported_issue_occurrences_agent_insert ON reported_issue_occurrences
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );

        -- UPDATE: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY reported_issue_occurrences_agent_update ON reported_issue_occurrences
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );

        -- DELETE: Use current_agent_type() which is SECURITY DEFINER
        CREATE POLICY reported_issue_occurrences_agent_delete ON reported_issue_occurrences
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND current_agent_type() = 'critic'
            );
    """)


def downgrade() -> None:
    """Restore inline subquery approach (for reference, not recommended)."""
    # Restore grading_decisions policies
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_agent_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_update ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_delete ON grading_decisions;

        CREATE POLICY grading_decisions_agent_insert ON grading_decisions
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
            );

        CREATE POLICY grading_decisions_agent_update ON grading_decisions
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
            );

        CREATE POLICY grading_decisions_agent_delete ON grading_decisions
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'grader'
            );
    """)

    # Restore reported_issues policies
    op.execute("""
        DROP POLICY IF EXISTS reported_issues_agent_insert ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_update ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_delete ON reported_issues;

        CREATE POLICY reported_issues_agent_insert ON reported_issues
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );

        CREATE POLICY reported_issues_agent_update ON reported_issues
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );

        CREATE POLICY reported_issues_agent_delete ON reported_issues
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );
    """)

    # Restore reported_issue_occurrences policies
    op.execute("""
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_insert ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_update ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_delete ON reported_issue_occurrences;

        CREATE POLICY reported_issue_occurrences_agent_insert ON reported_issue_occurrences
            FOR INSERT
            WITH CHECK (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );

        CREATE POLICY reported_issue_occurrences_agent_update ON reported_issue_occurrences
            FOR UPDATE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );

        CREATE POLICY reported_issue_occurrences_agent_delete ON reported_issue_occurrences
            FOR DELETE
            USING (
                agent_run_id = current_agent_run_id()
                AND (SELECT type_config->>'agent_type' FROM agent_runs WHERE agent_run_id = current_agent_run_id()) = 'critic'
            );
    """)
