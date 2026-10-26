"""Drop the app's automatic Thread title state."""

import sqlalchemy as sa
from alembic import op

revision = "0037_drop_auto_thread_titles"
down_revision = "0036_auto_thread_titles"
branch_labels = None
depends_on = None


_COLUMNS = (
    "title_revision",
    "title_claimed_at",
    "title_scan_cursor",
    "title_status",
    "title_user_managed",
    "auto_title_on_first_message",
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.drop_column("thread", column)


def downgrade() -> None:
    op.add_column(
        "thread", sa.Column("auto_title_on_first_message", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("thread", sa.Column("title_user_managed", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("thread", sa.Column("title_status", sa.Text(), server_default="waiting", nullable=False))
    op.add_column("thread", sa.Column("title_scan_cursor", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("thread", sa.Column("title_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("thread", sa.Column("title_revision", sa.Integer(), server_default="0", nullable=False))
