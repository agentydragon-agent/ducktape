"""Recreate grading_credit_sums view for agent_run_id.

This migration recreates the grading_credit_sums view and check_credit_sum
function that were dropped in 20251226000000 but never recreated.

The view was originally used by the check_credit_sum trigger to validate
that credit sums for grading decisions don't exceed 1.0 per occurrence.

Changes:
- Recreates grading_credit_sums view using agent_run_id instead of grader_run_id
- Updates check_credit_sum function to use agent_run_id

Revision ID: 20251231000001
Revises: 20251231000000
Create Date: 2025-12-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251231000001"
down_revision: str | Sequence[str] | None = "20251231000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recreate grading_credit_sums view and check_credit_sum function."""
    # Step 1: Recreate grading_credit_sums view using agent_run_id
    op.execute("""
        CREATE VIEW grading_credit_sums AS
        SELECT
            agent_run_id,
            target_tp_id,
            target_tp_occurrence_id,
            target_fp_id,
            target_fp_occurrence_id,
            SUM(credit) as total_credit,
            COUNT(*) as num_decisions
        FROM grading_decisions
        WHERE (target_tp_id IS NOT NULL OR target_fp_id IS NOT NULL)
        GROUP BY agent_run_id, target_tp_id, target_tp_occurrence_id,
                 target_fp_id, target_fp_occurrence_id
    """)

    op.execute("""
        COMMENT ON VIEW grading_credit_sums IS
        'Aggregate credit sums per (agent_run, occurrence) for enforcing credit ≤ 1.0 constraint.
        Used by check_credit_sum trigger function.'
    """)

    # Step 2: Grant access to agent_base role
    op.execute("GRANT SELECT ON grading_credit_sums TO agent_base")

    # Step 3: Drop and recreate check_credit_sum function using agent_run_id
    op.execute("DROP TRIGGER IF EXISTS enforce_credit_sum ON grading_decisions")
    op.execute("DROP FUNCTION IF EXISTS check_credit_sum() CASCADE")

    op.execute("""
        CREATE FUNCTION check_credit_sum() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_total FLOAT;
        BEGIN
            -- Skip if no target (no-match case)
            IF NEW.target_tp_id IS NULL AND NEW.target_fp_id IS NULL THEN
                RETURN NEW;
            END IF;

            -- Get current total from view (excluding NEW row)
            IF NEW.target_tp_id IS NOT NULL THEN
                SELECT COALESCE(total_credit, 0.0) INTO current_total
                FROM grading_credit_sums
                WHERE agent_run_id = NEW.agent_run_id
                  AND target_tp_id = NEW.target_tp_id
                  AND target_tp_occurrence_id = NEW.target_tp_occurrence_id;

                -- On UPDATE, subtract old credit from current total
                IF TG_OP = 'UPDATE' THEN
                    current_total := current_total - OLD.credit;
                END IF;
            ELSE
                SELECT COALESCE(total_credit, 0.0) INTO current_total
                FROM grading_credit_sums
                WHERE agent_run_id = NEW.agent_run_id
                  AND target_fp_id = NEW.target_fp_id
                  AND target_fp_occurrence_id = NEW.target_fp_occurrence_id;

                -- On UPDATE, subtract old credit from current total
                IF TG_OP = 'UPDATE' THEN
                    current_total := current_total - OLD.credit;
                END IF;
            END IF;

            -- Add new credit and validate
            current_total := COALESCE(current_total, 0.0) + NEW.credit;

            IF current_total > 1.0 THEN
                RAISE EXCEPTION 'Credit sum would exceed 1.0 for occurrence (current: %, new: %, total: %)',
                    current_total - NEW.credit, NEW.credit, current_total
                USING HINT = 'Each occurrence can have at most 1.0 total credit across all input issues';
            END IF;

            RETURN NEW;
        END;
        $$
    """)

    op.execute("""
        COMMENT ON FUNCTION check_credit_sum() IS
        'Trigger function that validates credit sums per occurrence do not exceed 1.0.
        Uses agent_run_id (not legacy grader_run_id).'
    """)

    # Step 4: Recreate trigger
    op.execute("""
        CREATE TRIGGER enforce_credit_sum
        BEFORE INSERT OR UPDATE ON grading_decisions
        FOR EACH ROW
        EXECUTE FUNCTION check_credit_sum()
    """)


def downgrade() -> None:
    """Drop grading_credit_sums view and check_credit_sum function."""
    op.execute("DROP TRIGGER IF EXISTS enforce_credit_sum ON grading_decisions")
    op.execute("DROP FUNCTION IF EXISTS check_credit_sum() CASCADE")
    op.execute("DROP VIEW IF EXISTS grading_credit_sums CASCADE")
