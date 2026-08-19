"""Pin every conversation to its chat-runtime implementation.

The identity belongs to ``conversation`` rather than ``sessions``: a replacement session continues
one thread and must inherit the implementation whose prompt, context, projection and replay
semantics made that thread. This release has exactly one implementation, so every existing row is
backfilled as ``claude_code`` and every new writer supplies the same value. There is no selector.

The physical column is ``TEXT`` with an ordinary CHECK, deliberately not a PostgreSQL enum. The
application still reads a closed enum, while the next runtime release can widen this constraint in
one transactional migration before it starts writing ``codex_app_server``; it does not need the
separate lifecycle and rollout choreography of altering a PostgreSQL enum type.

The column arrives nullable only inside this migration's transaction: add, total backfill, then
``SET NOT NULL``. No chat table is rebuilt or cleared, so conversations, attachments, sessions,
frames and the materialized conversation record remain intact.

Revision ID: 0087
Revises: 0086
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | None = None
depends_on: str | None = None

_COLUMN = "runtime_kind"
_CONSTRAINT = "ck_conversation_runtime_kind"


def upgrade() -> None:
    op.add_column("conversation", sa.Column(_COLUMN, sa.Text(), nullable=True))
    op.execute(sa.text("UPDATE conversation SET runtime_kind = 'claude_code'"))
    op.alter_column("conversation", _COLUMN, existing_type=sa.Text(), nullable=False)
    op.create_check_constraint(_CONSTRAINT, "conversation", "runtime_kind IN ('claude_code')")


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "conversation", type_="check")
    op.drop_column("conversation", _COLUMN)
