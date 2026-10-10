"""Record Action-backed MCP task identity and an immutable terminal state."""

import sqlalchemy as sa
from alembic import op

revision = "0023_action_mcp_task"
down_revision = "0022_connection_binding_change"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_request", sa.Column("mcp_task", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("action_request", sa.Column("mcp_terminal_state", sa.Text(), nullable=True))
    op.add_column("action_request", sa.Column("mcp_terminal_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("action_request", "mcp_terminal_at")
    op.drop_column("action_request", "mcp_terminal_state")
    op.drop_column("action_request", "mcp_task")
