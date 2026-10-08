"""Fence one durable Session identity per physical runner locator."""

from alembic import op

revision = "0002_unique_runner_locator"
down_revision = "0001_session_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ux_history_runner_locator",
        "session_history",
        ["sandbox_namespace", "sandbox_name", "sandbox_uid", "runner_session_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index("ux_history_runner_locator", table_name="session_history")
