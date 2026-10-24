"""Store app-owned per-Thread title automation state."""

import sqlalchemy as sa
from alembic import op

revision = "0036_auto_thread_titles"
down_revision = "0035_event_log_into_thread"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "thread", sa.Column("auto_title_on_first_message", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("thread", sa.Column("title_user_managed", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("thread", sa.Column("title_status", sa.Text(), server_default="waiting", nullable=False))
    op.add_column("thread", sa.Column("title_scan_cursor", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("thread", sa.Column("title_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("thread", sa.Column("title_revision", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("thread", "title_revision")
    op.drop_column("thread", "title_claimed_at")
    op.drop_column("thread", "title_scan_cursor")
    op.drop_column("thread", "title_status")
    op.drop_column("thread", "title_user_managed")
    op.drop_column("thread", "auto_title_on_first_message")
