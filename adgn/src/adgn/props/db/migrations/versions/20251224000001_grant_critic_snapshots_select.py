"""Grant critic_agent_template SELECT on snapshots table.

Revision ID: 20251224000001
Revises: 20251224000000
Create Date: 2025-12-24

The critic agent's init script needs to read the snapshots table to verify
database connectivity. Without this grant, critics cannot start because
the init script fails with "permission denied for table snapshots".

This is consistent with grader_agent_template which already has this grant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20251224000001"
down_revision: str | Sequence[str] | None = "20251224000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Grant SELECT on snapshots to critic_agent_template."""
    op.execute("GRANT SELECT ON TABLE snapshots TO critic_agent_template")


def downgrade() -> None:
    """Revoke SELECT on snapshots from critic_agent_template."""
    op.execute("REVOKE SELECT ON TABLE snapshots FROM critic_agent_template")
