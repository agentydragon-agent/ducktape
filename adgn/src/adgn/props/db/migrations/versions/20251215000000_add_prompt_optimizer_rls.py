"""Add RLS for prompt optimizer users

Revision ID: 20251215000000
Revises: 20251214000002
Create Date: 2025-12-15

Creates RLS function and policies for prompt optimizer temporary users.
Username pattern: prompt_optimizer_agent_{run_id}
Access: TRAIN split only (snapshots, TPs, FPs, examples)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251215000000"
down_revision: str | Sequence[str] | None = "20251214000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add prompt optimizer RLS function and policies."""
    # Create function to extract run_id from username
    op.execute("""
        CREATE OR REPLACE FUNCTION current_prompt_optimizer_run_id()
        RETURNS UUID AS $$
        DECLARE
            username TEXT;
            run_id_str TEXT;
            run_id_with_hyphens TEXT;
        BEGIN
            -- Use session_user instead of current_user because SECURITY DEFINER
            -- makes current_user return the function creator (postgres)
            username := session_user;

            -- Extract UUID from 'prompt_optimizer_agent_{uuid}'
            -- Note: UUID hyphens are replaced with underscores in the username to avoid
            -- PostgreSQL identifier syntax issues, so we convert them back before parsing
            IF username LIKE 'prompt_optimizer_agent_%' THEN
                -- Take everything after '_agent_'
                run_id_str := substring(username from position('_agent_' in username) + 7);
                -- Replace underscores with hyphens to restore UUID format
                run_id_with_hyphens := replace(run_id_str, '_', '-');

                -- Try to cast, return NULL if it fails
                BEGIN
                    RETURN run_id_with_hyphens::UUID;
                EXCEPTION WHEN OTHERS THEN
                    -- If UUID cast fails, log and return NULL
                    RAISE WARNING 'Failed to parse UUID from username: % (extracted: %, with hyphens: %)',
                        username, run_id_str, run_id_with_hyphens;
                    RETURN NULL;
                END;
            END IF;

            -- Return NULL for non-prompt-optimizer users (no filtering)
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
    """)

    # Enable RLS on training tables (if not already enabled by other migrations)
    for table in ["snapshots", "true_positives", "false_positives", "examples"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Create admin bypass policy (postgres user has full access)
    for table in ["snapshots", "true_positives", "false_positives", "examples"]:
        op.execute(f"""
            CREATE POLICY admin_full_access_{table} ON {table}
            FOR ALL TO postgres
            USING (true)
            WITH CHECK (true)
        """)

    # Create RLS policies for prompt optimizer users (TRAIN split only)

    # Snapshots: filter by split = 'TRAIN'
    op.execute("""
        CREATE POLICY prompt_optimizer_snapshots ON snapshots
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND split = 'train'::split_enum
        )
    """)

    # True Positives: filter by snapshot being in TRAIN split
    op.execute("""
        CREATE POLICY prompt_optimizer_true_positives ON true_positives
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND snapshot_slug IN (
                SELECT slug FROM snapshots WHERE split = 'train'::split_enum
            )
        )
    """)

    # False Positives: filter by snapshot being in TRAIN split
    op.execute("""
        CREATE POLICY prompt_optimizer_false_positives ON false_positives
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND snapshot_slug IN (
                SELECT slug FROM snapshots WHERE split = 'train'::split_enum
            )
        )
    """)

    # Examples: filter by snapshot being in TRAIN split
    op.execute("""
        CREATE POLICY prompt_optimizer_examples ON examples
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND snapshot_slug IN (
                SELECT slug FROM snapshots WHERE split = 'train'::split_enum
            )
        )
    """)


def downgrade() -> None:
    """Remove prompt optimizer RLS policies and function."""
    # Drop prompt optimizer policies
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_snapshots ON snapshots")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_true_positives ON true_positives")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_false_positives ON false_positives")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_examples ON examples")

    # Drop admin bypass policies
    for table in ["snapshots", "true_positives", "false_positives", "examples"]:
        op.execute(f"DROP POLICY IF EXISTS admin_full_access_{table} ON {table}")

    # Drop function
    op.execute("DROP FUNCTION IF EXISTS current_prompt_optimizer_run_id()")
