"""rename_critic_scopes_to_examples

Revision ID: df5f94e7b272
Revises: 362914e33560
Create Date: 2025-12-11 14:12:08.823501

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "df5f94e7b272"
down_revision: str | Sequence[str] | None = "362914e33560"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Drop FK constraint from critic_runs (if exists) - may not exist in all schemas
    op.execute("ALTER TABLE critic_runs DROP CONSTRAINT IF EXISTS critic_runs_critic_scope_id_fkey")

    # 2. Rename table
    op.rename_table("critic_scopes", "examples")

    # 3. Drop old serial PK constraint
    op.drop_constraint("critic_scopes_pkey", "examples", type_="primary")

    # 4. Drop id column
    op.drop_column("examples", "id")

    # 5. Add composite PK
    op.create_primary_key("examples_pkey", "examples", ["snapshot_slug", "files_hash"])

    # 6. Add index on files_hash in critic_runs for lookups
    op.create_index("ix_critic_runs_files_hash", "critic_runs", ["files_hash"])


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Drop index on critic_runs
    op.drop_index("ix_critic_runs_files_hash", "critic_runs")

    # 2. Drop composite PK
    op.drop_constraint("examples_pkey", "examples", type_="primary")

    # 3. Add back id column (serial)
    op.add_column("examples", sa.Column("id", sa.Integer(), autoincrement=True, nullable=False))

    # 4. Add back old PK constraint on id
    op.create_primary_key("critic_scopes_pkey", "examples", ["id"])

    # 5. Rename table back
    op.rename_table("examples", "critic_scopes")

    # 6. Restore FK constraint on critic_runs
    op.create_foreign_key(
        "critic_runs_critic_scope_id_fkey",
        "critic_runs",
        "critic_scopes",
        ["critic_scope_id"],
        ["id"],
        ondelete="SET NULL",
    )
