"""Add Agent Sandbox Claude chat sessions.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "claude_chat_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "operator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operators.operator_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("bridge_token_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("bridge_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('provisioning','ready','responding','closing','closed','failed')",
            name="ck_claude_chat_sessions_status",
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("idx_claude_chat_sessions_operator", "claude_chat_sessions", ["operator_id", "created_at"])
    op.create_table(
        "claude_chat_messages",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("claude_chat_sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user','assistant')", name="ck_claude_chat_messages_role"),
        sa.CheckConstraint(
            "status IN ('pending','streaming','complete','failed')", name="ck_claude_chat_messages_status"
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index("idx_claude_chat_messages_session_created", "claude_chat_messages", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_claude_chat_messages_session_created", table_name="claude_chat_messages")
    op.drop_table("claude_chat_messages")
    op.drop_index("idx_claude_chat_sessions_operator", table_name="claude_chat_sessions")
    op.drop_table("claude_chat_sessions")
