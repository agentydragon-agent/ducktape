"""Permit Codex app-server as an immutable conversation runtime.

The adapter and projection landed before production execution. Widen the ordinary TEXT check in one
transaction before Console can create a Codex-backed conversation; existing Claude rows are
untouched.

Revision ID: 0095
Revises: 0094
"""

from __future__ import annotations

from alembic import op

revision: str = "0095"
down_revision: str | None = "0094"
branch_labels: str | None = None
depends_on: str | None = None

_CONSTRAINT = "ck_conversation_runtime_kind"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "conversation", type_="check")
    op.create_check_constraint(_CONSTRAINT, "conversation", "runtime_kind IN ('claude_code', 'codex_app_server')")


def downgrade() -> None:
    # Fail closed if Codex conversations exist. PostgreSQL refuses to create the narrower check;
    # a downgrade must not retarget or delete durable conversation identity.
    op.drop_constraint(_CONSTRAINT, "conversation", type_="check")
    op.create_check_constraint(_CONSTRAINT, "conversation", "runtime_kind IN ('claude_code')")
