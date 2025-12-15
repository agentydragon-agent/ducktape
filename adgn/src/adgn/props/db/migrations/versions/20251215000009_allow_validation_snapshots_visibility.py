"""Allow prompt optimizer to see validation snapshot slugs (but not examples or ground truth)

Revision ID: 20251215000009
Revises: 20251215000008
Create Date: 2025-12-15 00:00:09

Changes:
- Update snapshots RLS policy to allow 'valid' split visibility (not just 'train')
- Agent can see validation snapshot slugs exist to target whole-snapshot runs
- Agent still CANNOT see validation examples table rows (examples remain train-only)
- Agent still CANNOT see validation ground truth (true_positives, false_positives remain train-only)
- Agent still CANNOT see validation execution traces (events remain train-only)

Workflow:
- Agent queries: SELECT slug FROM snapshots WHERE split='valid' -- works
- Agent queries: SELECT * FROM examples WHERE snapshot_slug IN (...valid slugs...) -- returns 0 rows (RLS blocks)
- Agent calls: run_critic_on_example(snapshot_slug='valid-slug', scope={"kind": "entire_snapshot"}, ...) -- works
- Validation constraint in run_critic tool validates scope is entire_snapshot for 'valid' split

Rationale:
- Agent needs to know what validation snapshots exist to run evaluations
- Snapshot slug alone is metadata, not ground truth
- Examples table stays train-only to prevent seeing file lists
- Ground truth and execution details remain hidden via separate RLS policies
"""

from alembic import op

revision = "20251215000009"
down_revision = "20251215000008"


def upgrade() -> None:
    """Update snapshots RLS policy to include 'valid' split."""

    # Drop existing policy
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_snapshots ON snapshots")

    # Recreate with 'valid' split included
    op.execute("""
        CREATE POLICY prompt_optimizer_snapshots ON snapshots
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND split IN ('train'::split_enum, 'valid'::split_enum)
        )
    """)


def downgrade() -> None:
    """Restore original train-only policy."""

    # Drop updated policy
    op.execute("DROP POLICY IF EXISTS prompt_optimizer_snapshots ON snapshots")

    # Restore original train-only policy
    op.execute("""
        CREATE POLICY prompt_optimizer_snapshots ON snapshots
        FOR SELECT
        USING (
            current_prompt_optimizer_run_id() IS NOT NULL
            AND split = 'train'::split_enum
        )
    """)
