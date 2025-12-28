"""Add only_matchable_from_files_hash to occurrence tables.

Adds sparse grading support: occurrences can specify which files a critique
must report on to match. NULL = cross-cutting, non-NULL = file-local.

Uses composite FK to file_sets(snapshot_slug, files_hash) to enforce
the file_set belongs to the same snapshot.

Revision ID: 20251227000004
Revises: 20251227000003
Create Date: 2025-12-27
"""

from alembic import op

revision = "20251227000004"
down_revision = "20251227000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column to true_positive_occurrences
    op.execute("""
        ALTER TABLE true_positive_occurrences
        ADD COLUMN only_matchable_from_files_hash TEXT
    """)

    op.execute("""
        ALTER TABLE true_positive_occurrences
        ADD CONSTRAINT fk_tp_occ_matchable_files
        FOREIGN KEY (snapshot_slug, only_matchable_from_files_hash)
        REFERENCES file_sets(snapshot_slug, files_hash) ON DELETE SET NULL
    """)

    # Add column to false_positive_occurrences
    op.execute("""
        ALTER TABLE false_positive_occurrences
        ADD COLUMN only_matchable_from_files_hash TEXT
    """)

    op.execute("""
        ALTER TABLE false_positive_occurrences
        ADD CONSTRAINT fk_fp_occ_matchable_files
        FOREIGN KEY (snapshot_slug, only_matchable_from_files_hash)
        REFERENCES file_sets(snapshot_slug, files_hash) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE false_positive_occurrences DROP CONSTRAINT fk_fp_occ_matchable_files")
    op.execute("ALTER TABLE false_positive_occurrences DROP COLUMN only_matchable_from_files_hash")
    op.execute("ALTER TABLE true_positive_occurrences DROP CONSTRAINT fk_tp_occ_matchable_files")
    op.execute("ALTER TABLE true_positive_occurrences DROP COLUMN only_matchable_from_files_hash")
