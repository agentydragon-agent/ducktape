"""Migrate reported_issues from critic_run_id to agent_run_id.

This migration changes the FK reference from critic_runs to agent_runs,
enabling the unified agent model where all agent types use AgentRun.

Changes:
- agent_runs: Add status and completion_summary columns
- agent_run_status_enum: New enum for agent run status
- reported_issues: critic_run_id → agent_run_id (FK to agent_runs)
- reported_issue_occurrences: critic_run_id → agent_run_id
- Updates compound FK constraints accordingly

Revision ID: 20251224000000
Revises: 20251223000000
Create Date: 2025-12-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251224000000"
down_revision: str | Sequence[str] | None = "20251223000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Migrate reported_issues to use agent_run_id instead of critic_run_id."""
    # Step 0: Add status and completion_summary to agent_runs
    op.execute("""
        -- Create agent run status enum (matches CriticRunStatus for compatibility)
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'agent_run_status_enum') THEN
                CREATE TYPE agent_run_status_enum AS ENUM (
                    'in_progress',
                    'completed',
                    'max_turns_exceeded',
                    'context_length_exceeded',
                    'reported_failure'
                );
            END IF;
        END
        $$;

        -- Add status column to agent_runs
        ALTER TABLE agent_runs
            ADD COLUMN IF NOT EXISTS status agent_run_status_enum NOT NULL DEFAULT 'in_progress';

        -- Add completion_summary column to agent_runs
        ALTER TABLE agent_runs
            ADD COLUMN IF NOT EXISTS completion_summary TEXT;

        -- Add updated_at column to agent_runs
        ALTER TABLE agent_runs
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

        COMMENT ON COLUMN agent_runs.status IS
            'Run status: in_progress, completed, max_turns_exceeded, context_length_exceeded, or reported_failure';
        COMMENT ON COLUMN agent_runs.completion_summary IS
            'Markdown summary from agent when status=completed, or error message when status=reported_failure';
    """)

    # Step 1: Drop existing FK constraints
    op.execute("""
        -- Drop FK from reported_issue_occurrences to reported_issues
        ALTER TABLE reported_issue_occurrences
            DROP CONSTRAINT IF EXISTS reported_issue_occurrences_critic_run_id_reported_issue_id_fkey;

        -- Drop FK from reported_issues to critic_runs
        ALTER TABLE reported_issues
            DROP CONSTRAINT IF EXISTS reported_issues_critic_run_id_fkey;
    """)

    # Step 2: Rename columns
    op.execute("""
        -- Rename critic_run_id to agent_run_id in reported_issues
        ALTER TABLE reported_issues
            RENAME COLUMN critic_run_id TO agent_run_id;

        -- Rename critic_run_id to agent_run_id in reported_issue_occurrences
        ALTER TABLE reported_issue_occurrences
            RENAME COLUMN critic_run_id TO agent_run_id;
    """)

    # Step 3: Add new FK constraints pointing to agent_runs
    op.execute("""
        -- Add FK from reported_issues to agent_runs
        ALTER TABLE reported_issues
            ADD CONSTRAINT reported_issues_agent_run_id_fkey
            FOREIGN KEY (agent_run_id) REFERENCES agent_runs(agent_run_id)
            ON DELETE CASCADE;

        -- Add FK from reported_issue_occurrences to reported_issues (compound)
        ALTER TABLE reported_issue_occurrences
            ADD CONSTRAINT reported_issue_occurrences_agent_run_id_issue_id_fkey
            FOREIGN KEY (agent_run_id, reported_issue_id)
            REFERENCES reported_issues(agent_run_id, issue_id)
            ON DELETE CASCADE;
    """)

    # Step 4: Create current_agent_run_id() function
    # This function extracts agent run ID from critic_agent_{uuid} username pattern
    # Named consistently (current_agent_run_id rather than current_critic_run_id)
    # since we're now using agent_run_id in the schema
    op.execute("""
        CREATE OR REPLACE FUNCTION current_agent_run_id() RETURNS uuid
        LANGUAGE plpgsql STABLE
        AS $$
        DECLARE
            run_id_text TEXT;
        BEGIN
            -- Extract UUID from critic_agent_{uuid} pattern
            run_id_text := SUBSTRING(current_user FROM 'critic_agent_([0-9a-f-]+)');
            IF run_id_text IS NULL THEN
                RETURN NULL;
            END IF;
            RETURN run_id_text::UUID;
        END;
        $$;

        COMMENT ON FUNCTION current_agent_run_id() IS
            'Extracts agent run UUID from database username (critic_agent_{uuid} pattern). Used by RLS policies.';
    """)

    # Step 5: Update RLS policies if they reference critic_run_id
    # Drop old policies and create new ones with agent_run_id
    op.execute("""
        -- Drop old RLS policies that reference critic_run_id
        DROP POLICY IF EXISTS reported_issues_critic_select ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_critic_insert ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_critic_delete ON reported_issues;
        DROP POLICY IF EXISTS reported_issue_occurrences_critic_select ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_critic_insert ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_critic_delete ON reported_issue_occurrences;

        -- Create new RLS policies using current_agent_run_id()
        -- reported_issues policies
        CREATE POLICY reported_issues_agent_select ON reported_issues
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issues_agent_insert ON reported_issues
            FOR INSERT
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issues_agent_delete ON reported_issues
            FOR DELETE
            USING (agent_run_id = current_agent_run_id());

        -- reported_issue_occurrences policies
        CREATE POLICY reported_issue_occurrences_agent_select ON reported_issue_occurrences
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issue_occurrences_agent_insert ON reported_issue_occurrences
            FOR INSERT
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY reported_issue_occurrences_agent_delete ON reported_issue_occurrences
            FOR DELETE
            USING (agent_run_id = current_agent_run_id());
    """)

    # Step 6: Update comments
    op.execute("""
        COMMENT ON COLUMN reported_issues.agent_run_id IS
            'FK to agent_runs - identifies which agent run reported this issue';

        COMMENT ON COLUMN reported_issue_occurrences.agent_run_id IS
            'FK to agent_runs (denormalized from reported_issues for RLS efficiency)';
    """)


def downgrade() -> None:
    """Revert reported_issues back to critic_run_id."""
    # Step 0: Drop status and completion_summary from agent_runs
    op.execute("""
        ALTER TABLE agent_runs DROP COLUMN IF EXISTS status;
        ALTER TABLE agent_runs DROP COLUMN IF EXISTS completion_summary;
        ALTER TABLE agent_runs DROP COLUMN IF EXISTS updated_at;
        DROP TYPE IF EXISTS agent_run_status_enum;
    """)

    # Step 1: Drop new FK constraints
    op.execute("""
        ALTER TABLE reported_issue_occurrences
            DROP CONSTRAINT IF EXISTS reported_issue_occurrences_agent_run_id_issue_id_fkey;

        ALTER TABLE reported_issues
            DROP CONSTRAINT IF EXISTS reported_issues_agent_run_id_fkey;
    """)

    # Step 2: Drop new RLS policies
    op.execute("""
        DROP POLICY IF EXISTS reported_issues_agent_select ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_insert ON reported_issues;
        DROP POLICY IF EXISTS reported_issues_agent_delete ON reported_issues;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_select ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_insert ON reported_issue_occurrences;
        DROP POLICY IF EXISTS reported_issue_occurrences_agent_delete ON reported_issue_occurrences;
    """)

    # Step 2.5: Drop current_agent_run_id() function
    op.execute("DROP FUNCTION IF EXISTS current_agent_run_id();")

    # Step 3: Rename columns back
    op.execute("""
        ALTER TABLE reported_issues
            RENAME COLUMN agent_run_id TO critic_run_id;

        ALTER TABLE reported_issue_occurrences
            RENAME COLUMN agent_run_id TO critic_run_id;
    """)

    # Step 4: Restore original FK constraints pointing to critic_runs
    op.execute("""
        ALTER TABLE reported_issues
            ADD CONSTRAINT reported_issues_critic_run_id_fkey
            FOREIGN KEY (critic_run_id) REFERENCES critic_runs(id)
            ON DELETE CASCADE;

        ALTER TABLE reported_issue_occurrences
            ADD CONSTRAINT reported_issue_occurrences_critic_run_id_reported_issue_id_fkey
            FOREIGN KEY (critic_run_id, reported_issue_id)
            REFERENCES reported_issues(critic_run_id, issue_id)
            ON DELETE CASCADE;
    """)

    # Step 5: Restore original RLS policies
    op.execute("""
        CREATE POLICY reported_issues_critic_select ON reported_issues
            FOR SELECT
            USING (critic_run_id = current_critic_run_id());

        CREATE POLICY reported_issues_critic_insert ON reported_issues
            FOR INSERT
            WITH CHECK (critic_run_id = current_critic_run_id());

        CREATE POLICY reported_issues_critic_delete ON reported_issues
            FOR DELETE
            USING (critic_run_id = current_critic_run_id());

        CREATE POLICY reported_issue_occurrences_critic_select ON reported_issue_occurrences
            FOR SELECT
            USING (critic_run_id = current_critic_run_id());

        CREATE POLICY reported_issue_occurrences_critic_insert ON reported_issue_occurrences
            FOR INSERT
            WITH CHECK (critic_run_id = current_critic_run_id());

        CREATE POLICY reported_issue_occurrences_critic_delete ON reported_issue_occurrences
            FOR DELETE
            USING (critic_run_id = current_critic_run_id());
    """)
