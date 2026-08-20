"""Admit an idle session before lazy sandbox allocation starts writing one.

An idle session exists without a SandboxClaim. This release teaches prompt admission and allocation
to move one to ``provisioning`` and create the claim, but deliberately contains no idle writer. The
follow-up only changes session creation after this parser has reached every replica.

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
    op.alter_column("sessions", "bridge_token_fingerprint", nullable=True)
    op.alter_column("sessions", "lease_expires_at", nullable=True)
    op.create_check_constraint(
        "ck_sessions_idle_bridge_token",
        "sessions",
        "(status = 'idle' AND bridge_token_fingerprint IS NULL) OR "
        "(status <> 'idle' AND (bridge_token_fingerprint IS NOT NULL OR status IN ('closing','closed','failed')))",
    )
    op.create_check_constraint(
        "ck_sessions_idle_lease",
        "sessions",
        "(status = 'idle' AND lease_expires_at IS NULL) OR "
        "(status <> 'idle' AND (lease_expires_at IS NOT NULL OR status IN ('closing','closed','failed')))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sessions_idle_lease", "sessions", type_="check")
    op.alter_column("sessions", "lease_expires_at", nullable=False)
    op.drop_constraint("ck_sessions_idle_bridge_token", "sessions", type_="check")
    op.alter_column("sessions", "bridge_token_fingerprint", nullable=False)
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _WITHOUT_IDLE)
