"""add_is_whole_snapshot_to_examples

Add is_whole_snapshot column and make files/files_hash nullable.

Revision ID: 20251214000001
Revises: 20251214000000
Create Date: 2025-12-14 00:00:01.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20251214000001"
down_revision: str | Sequence[str] | None = "20251214000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add is_whole_snapshot column and make files/files_hash nullable.

    This supports two kinds of training examples:
    1. Whole-snapshot examples: is_whole_snapshot=TRUE, files=NULL, files_hash=NULL
       - One per snapshot (uniqueness enforced by partial index)
    2. File-set examples: is_whole_snapshot=FALSE, files=JSONB list, files_hash=SHA256
       - Multiple per snapshot (uniqueness on snapshot_slug + files_hash via partial index)

    Strategy:
    - Add surrogate 'id' column as new PRIMARY KEY (auto-incrementing)
    - Drop old composite PK (snapshot_slug, files_hash)
    - Add is_whole_snapshot column
    - Make files and files_hash nullable
    - Add partial unique indexes for both example types
    - Add check constraint to enforce data integrity
    """

    # 1. Add surrogate id column (nullable initially for existing rows)
    op.add_column("examples", sa.Column("id", sa.Integer(), nullable=True, autoincrement=False))

    # 2. Create sequence for id column
    op.execute("CREATE SEQUENCE examples_id_seq")
    op.execute("ALTER TABLE examples ALTER COLUMN id SET DEFAULT nextval('examples_id_seq')")

    # 3. Populate id for existing rows (assign sequential IDs)
    op.execute("UPDATE examples SET id = nextval('examples_id_seq')")

    # 4. Make id NOT NULL and set sequence ownership
    op.alter_column("examples", "id", nullable=False)
    op.execute("ALTER SEQUENCE examples_id_seq OWNED BY examples.id")

    # 5. Drop old composite primary key
    op.drop_constraint("examples_pkey", "examples", type_="primary")

    # 6. Create new primary key on id
    op.create_primary_key("examples_pkey", "examples", ["id"])

    # 7. Add is_whole_snapshot column (NOT NULL, default FALSE for existing rows)
    op.add_column(
        "examples", sa.Column("is_whole_snapshot", sa.Boolean(), nullable=False, server_default=sa.text("FALSE"))
    )

    # 8. Make files nullable (was NOT NULL)
    op.alter_column("examples", "files", nullable=True)

    # 9. Make files_hash nullable (was NOT NULL)
    op.alter_column("examples", "files_hash", nullable=True)

    # 10. Add partial unique index for whole-snapshot examples
    #     Only one whole-snapshot example per snapshot
    op.create_index(
        "uq_examples_whole_snapshot",
        "examples",
        ["snapshot_slug"],
        unique=True,
        postgresql_where=sa.text("is_whole_snapshot = TRUE"),
    )

    # 11. Add partial unique index for file-set examples
    #     Multiple file-set examples per snapshot, unique by (snapshot_slug, files_hash)
    op.create_index(
        "uq_examples_file_set",
        "examples",
        ["snapshot_slug", "files_hash"],
        unique=True,
        postgresql_where=sa.text("is_whole_snapshot = FALSE"),
    )

    # 12. Add check constraint to enforce data integrity
    #     Whole-snapshot: is_whole_snapshot=TRUE AND files IS NULL AND files_hash IS NULL
    #     File-set: is_whole_snapshot=FALSE AND files IS NOT NULL AND files_hash IS NOT NULL
    op.create_check_constraint(
        "ck_examples_snapshot_type",
        "examples",
        sa.text(
            "(is_whole_snapshot = TRUE AND files IS NULL AND files_hash IS NULL) OR "
            "(is_whole_snapshot = FALSE AND files IS NOT NULL AND files_hash IS NOT NULL)"
        ),
    )


def downgrade() -> None:
    """Revert changes."""

    # Drop check constraint
    op.drop_constraint("ck_examples_snapshot_type", "examples", type_="check")

    # Drop partial unique indexes
    op.drop_index("uq_examples_file_set", "examples")
    op.drop_index("uq_examples_whole_snapshot", "examples")

    # Make files NOT NULL again (must do before restoring composite PK)
    op.alter_column("examples", "files", nullable=False)

    # Make files_hash NOT NULL again (must do before restoring composite PK)
    op.alter_column("examples", "files_hash", nullable=False)

    # Remove is_whole_snapshot column
    op.drop_column("examples", "is_whole_snapshot")

    # Drop new PK on id
    op.drop_constraint("examples_pkey", "examples", type_="primary")

    # Drop sequence and id column
    op.execute("DROP SEQUENCE IF EXISTS examples_id_seq")
    op.drop_column("examples", "id")

    # Restore old composite PK
    op.create_primary_key("examples_pkey", "examples", ["snapshot_slug", "files_hash"])
