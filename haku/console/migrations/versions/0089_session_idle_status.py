"""Admit an idle session before lazy sandbox allocation starts writing one.

An idle session exists without a SandboxClaim. The follow-up release lets the first prompt move it
to ``provisioning`` and create the claim; this migration deliberately contains no writer.

The split is required by the Console's zero-unavailable rolling deployment. ``sessions.status`` is
parsed into a closed application enum, so a previous replica cannot read an ``idle`` row. Widening
the constraint and enum one release first keeps both directions of the roll compatible.

Revision ID: 0089
Revises: 0088
"""

from __future__ import annotations

from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "sessions"
_CONSTRAINT = "ck_sessions_status"
_WITHOUT_IDLE = "status IN ('provisioning','ready','responding','closing','closed','failed')"
_WITH_IDLE = "status IN ('idle','provisioning','ready','responding','closing','closed','failed')"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _WITH_IDLE)


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _WITHOUT_IDLE)
