"""Move the semantic index from its retired physical schema name.

``haku/recall_index`` has been the implementation name since the source-tree move, but the
self-healing derived tables were still physically owned by ``state_index``.  An Alembic schema
rename moves the tables, constraints, and indexes together; copying them would require a second
publication protocol and risks serving stale occurrences.

The index is deliberately allowed the same brief rolling-deploy incompatibility as migration 0061:
an older replica still issuing ``state_index`` queries fails rather than returning an incomplete
answer, while the new replica sees the unchanged derived data under ``recall_index``.  No source
content is discarded and a failed transaction leaves the old schema name intact.

Revision ID: 0083
Revises: 0082
"""

from __future__ import annotations

from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | None = None
depends_on: str | None = None

_OLD_SCHEMA = "state_index"
_NEW_SCHEMA = "recall_index"


def upgrade() -> None:
    op.execute(f"ALTER SCHEMA {_OLD_SCHEMA} RENAME TO {_NEW_SCHEMA}")


def downgrade() -> None:
    op.execute(f"ALTER SCHEMA {_NEW_SCHEMA} RENAME TO {_OLD_SCHEMA}")
