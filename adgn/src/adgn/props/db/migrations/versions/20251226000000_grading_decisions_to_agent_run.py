"""Migrate grading_decisions from grader_run_id to agent_run_id.

This migration changes the FK reference from grader_runs to agent_runs,
continuing the unified agent model where all agent types use AgentRun.

Changes:
- grading_decisions: grader_run_id → agent_run_id (FK to agent_runs)
- Updates RLS policies for grading_decisions to use current_agent_run_id()
- Updates the input_issue_existence check trigger

The grader_runs table still exists at this point (dropped in a later migration).
This migration only changes the FK target.

Revision ID: 20251226000000
Revises: 20251225000000
Create Date: 2025-12-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251226000000"
down_revision: str | Sequence[str] | None = "20251225000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Migrate grading_decisions to use agent_run_id instead of grader_run_id."""
    # Step 0: Drop views and policies that depend on grading_decisions.grader_run_id
    # These will be recreated in a later migration (20251226000002)
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")
    op.execute("DROP VIEW IF EXISTS pareto_frontier_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS critic_run_occurrence_stats CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS grading_credit_totals CASCADE")
    op.execute("DROP VIEW IF EXISTS grading_credit_sums CASCADE")
    op.execute("DROP POLICY IF EXISTS grading_decisions_rls ON grading_decisions")

    # Step 1: Add agent_run_id column (nullable initially for backfill)
    op.execute("""
        ALTER TABLE grading_decisions
            ADD COLUMN IF NOT EXISTS agent_run_id UUID;

        COMMENT ON COLUMN grading_decisions.agent_run_id IS
            'FK to agent_runs - identifies which grader agent run created this decision';
    """)

    # Step 2: Backfill agent_run_id from grader_runs
    # grader_runs has a transcript_id which corresponds to agent_run_id in agent_runs
    # Wait - grader_runs.id is UUID, and we need to find the corresponding agent_run
    # Actually, the grader's AgentRun would have been created separately...
    # For now, we'll handle this by requiring no existing grading_decisions during migration
    # OR we can match via transcript_id (grader_runs.transcript_id = agent_runs.agent_run_id for graders)
    op.execute("""
        -- Backfill: grader_runs.transcript_id is the agent_run_id for graders
        -- (graders create AgentRun with agent_run_id = transcript_id)
        UPDATE grading_decisions gd
        SET agent_run_id = gr.transcript_id
        FROM grader_runs gr
        WHERE gd.grader_run_id = gr.id
          AND gd.agent_run_id IS NULL;
    """)

    # Step 3: Make agent_run_id NOT NULL
    op.execute("""
        ALTER TABLE grading_decisions
            ALTER COLUMN agent_run_id SET NOT NULL;
    """)

    # Step 4: Drop old FK and default
    op.execute("""
        -- Drop the grader_run_id FK constraint
        ALTER TABLE grading_decisions
            DROP CONSTRAINT IF EXISTS grading_decisions_grader_run_id_fkey;

        -- Drop the server_default (FetchedValue) from grader_run_id
        ALTER TABLE grading_decisions
            ALTER COLUMN grader_run_id DROP DEFAULT;
    """)

    # Step 5: Drop grader_run_id column
    op.execute("""
        ALTER TABLE grading_decisions
            DROP COLUMN IF EXISTS grader_run_id;
    """)

    # Step 6: Add new FK to agent_runs
    op.execute("""
        ALTER TABLE grading_decisions
            ADD CONSTRAINT grading_decisions_agent_run_id_fkey
            FOREIGN KEY (agent_run_id) REFERENCES agent_runs(agent_run_id)
            ON DELETE CASCADE;
    """)

    # Step 7: Update the input_issue_existence check function
    # This function validates that input_issue_id exists in reported_issues for the graded critic
    # We need to update it to work via agent_runs instead of grader_runs
    op.execute("""
        CREATE OR REPLACE FUNCTION check_input_issue_exists()
        RETURNS TRIGGER AS $$
        DECLARE
            graded_critic_run_id UUID;
        BEGIN
            -- Get the critic run ID being graded from the grader's type_config
            SELECT (type_config->>'graded_agent_run_id')::UUID INTO graded_critic_run_id
            FROM agent_runs
            WHERE agent_run_id = NEW.agent_run_id;

            IF graded_critic_run_id IS NULL THEN
                RAISE EXCEPTION 'Grader run % has no graded_agent_run_id in type_config', NEW.agent_run_id;
            END IF;

            -- Check that the input_issue_id exists in reported_issues for that critic run
            IF NOT EXISTS (
                SELECT 1 FROM reported_issues
                WHERE agent_run_id = graded_critic_run_id
                  AND issue_id = NEW.input_issue_id
            ) THEN
                RAISE EXCEPTION 'Input issue % does not exist in critic run %',
                    NEW.input_issue_id, graded_critic_run_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        COMMENT ON FUNCTION check_input_issue_exists() IS
            'Validates that grading_decisions.input_issue_id exists in the graded critic run''s reported_issues';
    """)

    # Step 8: Update RLS policies for grading_decisions
    # First, drop old policies
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_grader_select ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_grader_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_grader_delete ON grading_decisions;
    """)

    # Create new policies using current_agent_run_id()
    op.execute("""
        -- Graders can SELECT/INSERT/DELETE their own decisions
        CREATE POLICY grading_decisions_agent_select ON grading_decisions
            FOR SELECT
            USING (agent_run_id = current_agent_run_id());

        CREATE POLICY grading_decisions_agent_insert ON grading_decisions
            FOR INSERT
            WITH CHECK (agent_run_id = current_agent_run_id());

        CREATE POLICY grading_decisions_agent_delete ON grading_decisions
            FOR DELETE
            USING (agent_run_id = current_agent_run_id());
    """)

    # Step 9: Add index on agent_run_id
    op.execute("""
        CREATE INDEX IF NOT EXISTS grading_decisions_agent_run_id_idx
            ON grading_decisions(agent_run_id);
    """)


def downgrade() -> None:
    """Revert grading_decisions back to grader_run_id."""
    # Step 1: Drop index
    op.execute("""
        DROP INDEX IF EXISTS grading_decisions_agent_run_id_idx;
    """)

    # Step 2: Drop new RLS policies
    op.execute("""
        DROP POLICY IF EXISTS grading_decisions_agent_select ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_insert ON grading_decisions;
        DROP POLICY IF EXISTS grading_decisions_agent_delete ON grading_decisions;
    """)

    # Step 3: Restore old check_input_issue_exists function
    op.execute("""
        CREATE OR REPLACE FUNCTION check_input_issue_exists()
        RETURNS TRIGGER AS $$
        DECLARE
            critic_run_id UUID;
        BEGIN
            -- Get the critic run ID from grader_run
            SELECT gr.critic_run_id INTO critic_run_id
            FROM grader_runs gr
            WHERE gr.id = NEW.grader_run_id;

            -- Check that the input_issue_id exists in reported_issues
            IF NOT EXISTS (
                SELECT 1 FROM reported_issues ri
                INNER JOIN critic_runs cr ON ri.critic_run_id = cr.id
                WHERE cr.id = critic_run_id
                  AND ri.issue_id = NEW.input_issue_id
            ) THEN
                RAISE EXCEPTION 'Input issue % does not exist in critic run %',
                    NEW.input_issue_id, critic_run_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Step 4: Add grader_run_id column back
    op.execute("""
        ALTER TABLE grading_decisions
            ADD COLUMN IF NOT EXISTS grader_run_id UUID;
    """)

    # Step 5: Backfill grader_run_id from agent_run_id
    # Find grader_runs with matching transcript_id
    op.execute("""
        UPDATE grading_decisions gd
        SET grader_run_id = gr.id
        FROM grader_runs gr
        WHERE gd.agent_run_id = gr.transcript_id
          AND gd.grader_run_id IS NULL;
    """)

    # Step 6: Make grader_run_id NOT NULL and add FK
    op.execute("""
        ALTER TABLE grading_decisions
            ALTER COLUMN grader_run_id SET NOT NULL;

        ALTER TABLE grading_decisions
            ADD CONSTRAINT grading_decisions_grader_run_id_fkey
            FOREIGN KEY (grader_run_id) REFERENCES grader_runs(id)
            ON DELETE CASCADE;
    """)

    # Step 7: Drop agent_run_id FK and column
    op.execute("""
        ALTER TABLE grading_decisions
            DROP CONSTRAINT IF EXISTS grading_decisions_agent_run_id_fkey;

        ALTER TABLE grading_decisions
            DROP COLUMN IF EXISTS agent_run_id;
    """)

    # Step 8: Restore old RLS policies
    op.execute("""
        CREATE POLICY grading_decisions_grader_select ON grading_decisions
            FOR SELECT
            USING (grader_run_id = current_grader_run_id());

        CREATE POLICY grading_decisions_grader_insert ON grading_decisions
            FOR INSERT
            WITH CHECK (grader_run_id = current_grader_run_id());

        CREATE POLICY grading_decisions_grader_delete ON grading_decisions
            FOR DELETE
            USING (grader_run_id = current_grader_run_id());
    """)
