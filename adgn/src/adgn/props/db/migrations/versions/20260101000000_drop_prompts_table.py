"""Drop prompts table.

Revision ID: 20260101000000
Revises: 20251231000005
Create Date: 2025-12-21

The prompts table is no longer needed - prompts are now stored in agent
definition archives (in agent_defs/<agent>/AGENT.md) rather than being
content-addressed in the database.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260101000000"
down_revision: str | Sequence[str] | None = "20250101000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the prompts table."""
    op.drop_table("prompts")


def downgrade() -> None:
    """Recreate the prompts table."""
    op.create_table(
        "prompts",
        sa.Column("prompt_sha256", sa.String(64), primary_key=True),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column(
            "creator_agent_run_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.agent_run_id"),
            nullable=True,
            index=True,
        ),
        sa.Column("template_file_path", sa.Text, nullable=True, index=True),
        sa.Column("created_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
