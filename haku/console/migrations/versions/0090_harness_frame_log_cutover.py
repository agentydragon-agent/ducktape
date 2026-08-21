"""Cut over the frame log to the opaque harness-frame vocabulary.

This is intentionally incompatible with pre-v3 bridge runners. Existing runners cannot negotiate
protocol version 3 and are refused/cleaned up by the runtime. The migration preserves operators,
credentials, approvals, provider connections, conversations and Matrix attachments, but removes
session/chat-derived rows so no old identity-based frame log can be interpreted as a v3 log.

Revision ID: 0090
Revises: 0089
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Keep the conversation and attachment rows: Matrix room associations are durable channel
    # state. Everything below is session/chat-derived and is recreated by the normal supervisor.
    # Delete children explicitly because some older deployments carried nullable/non-cascading
    # references to the conversation record.
    op.execute("DELETE FROM conversation_prompt")
    op.execute("DELETE FROM conversation_event")
    op.execute("DELETE FROM conversation_item")
    op.execute("DELETE FROM conversation_turn")
    op.execute("DELETE FROM sessions")

    op.drop_index("uq_session_frames_uid", table_name="session_frames")
    op.drop_index("idx_session_frames_runner_seq", table_name="session_frames")
    op.drop_column("session_frames", "frame_uid")
    op.create_check_constraint("ck_session_frames_kind", "session_frames", "kind IN ('harness_frame', 'setup_output')")
    op.create_index(
        "uq_session_frames_runner_seq",
        "session_frames",
        ["session_id", "runner_seq"],
        unique=True,
        postgresql_where=sa.text("runner_seq IS NOT NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("the v3 harness-frame cutover is intentionally irreversible")
