"""Add RLS for evaluation results tables (critic_runs, critiques, grader_runs)

Revision ID: 20251215000003
Revises: 20251215000002
Create Date: 2025-12-15

Creates RLS policies for evaluation results tables to filter by snapshot split.
Prompt optimizer users get access to TRAIN split evaluation results.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251215000003"
down_revision: str | Sequence[str] | None = "20251215000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add RLS policies for evaluation results tables."""
    # Enable RLS on evaluation results tables
    for table in ["critic_runs", "critiques", "grader_runs"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Create admin bypass policy (postgres user has full access)
    for table in ["critic_runs", "critiques", "grader_runs"]:
        op.execute(f"""
            CREATE POLICY admin_full_access_{table} ON {table}
            FOR ALL TO postgres
            USING (true)
            WITH CHECK (true)
        """)

    # Critic runs: filter by snapshot split (join with snapshots)
    op.execute("""
        CREATE POLICY prompt_optimizer_critic_runs ON critic_runs
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND snapshot_slug IN (
                SELECT slug FROM snapshots WHERE split = 'train'::split_enum
            )
        )
    """)

    # Critiques: filter by snapshot split
    op.execute("""
        CREATE POLICY prompt_optimizer_critiques ON critiques
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND snapshot_slug IN (
                SELECT slug FROM snapshots WHERE split = 'train'::split_enum
            )
        )
    """)

    # Grader runs: filter by snapshot split
    op.execute("""
        CREATE POLICY prompt_optimizer_grader_runs ON grader_runs
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND snapshot_slug IN (
                SELECT slug FROM snapshots WHERE split = 'train'::split_enum
            )
        )
    """)


def downgrade() -> None:
    """Remove RLS policies for evaluation results tables."""
    # Drop prompt optimizer policies
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_critic_runs ON critic_runs")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_critiques ON critiques")
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_grader_runs ON grader_runs")

    # Drop admin bypass policies
    for table in ["critic_runs", "critiques", "grader_runs"]:
        op.execute(f"DROP POLICY IF EXISTS admin_full_access_{table} ON {table}")

    # Note: We don't disable RLS on these tables in downgrade because other policies might exist
    # (e.g., clustering policies). The policies are table-specific, so dropping them is sufficient.
