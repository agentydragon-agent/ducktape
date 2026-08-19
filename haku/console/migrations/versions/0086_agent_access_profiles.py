"""Expand durable Agent authority with config-defined access-profile references.

Profiles stay in the reviewed deployment configuration, so these nullable textual references do
not have a database foreign key. Existing policy assignments remain mapped through the rolling
deployment; a later contract migration drops those legacy columns after every replica is profile
aware.

Revision ID: 0086
Revises: 0085
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("access_profile_id", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_agents_access_profile_id_nonempty", "agents", "access_profile_id IS NULL OR btrim(access_profile_id) <> ''"
    )
    op.add_column("enrollment_interactions", sa.Column("access_profile_id", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_enrollment_interactions_access_profile_id_nonempty",
        "enrollment_interactions",
        "access_profile_id IS NULL OR btrim(access_profile_id) <> ''",
    )


def downgrade() -> None:
    op.drop_constraint("ck_enrollment_interactions_access_profile_id_nonempty", "enrollment_interactions")
    op.drop_column("enrollment_interactions", "access_profile_id")
    op.drop_constraint("ck_agents_access_profile_id_nonempty", "agents")
    op.drop_column("agents", "access_profile_id")
