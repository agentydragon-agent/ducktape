"""Separate Recall source materialization from embedding completion.

Git and chat source writers now publish chunks as soon as they have materialized
their source. A shared embedding worker fills model-specific vectors later, so
the source-state rows no longer claim that a particular embedding model was
complete when the source was observed.

Revision ID: 0088
Revises: 0087
"""

from __future__ import annotations

from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "recall_index"


def upgrade() -> None:
    op.drop_constraint("ck_git_sync_state_indexed_half", "git_sync_state", schema=SCHEMA, type_="check")
    op.drop_column("git_sync_state", "model_key", schema=SCHEMA)
    op.create_check_constraint(
        "ck_git_sync_state_indexed_half",
        "git_sync_state",
        "(commit_sha IS NULL) = (chunker_key IS NULL) AND (commit_sha IS NULL) = (synced_at IS NULL)",
        schema=SCHEMA,
    )
    op.drop_column("chat_sessions", "model_key", schema=SCHEMA)


def downgrade() -> None:
    raise RuntimeError(
        "0087 is intentionally irreversible: restoring source-side model_key columns would fabricate "
        "embedding-completion claims that the shared worker no longer records"
    )
