"""Add scope architecture (scope_hash, scope JSONB) to examples and critic_runs

Revision ID: 20251215000000
Revises: 20251214000000
Create Date: 2025-12-15 00:00:00.000000

Changes:
1. Add scope_hash and scope columns to examples table
2. Populate scope from files (ExplicitFileScope)
3. Add scope_hash to critic_runs table
4. Populate critic_runs.scope_hash by joining to examples
5. Drop old files and files_hash columns
6. Update foreign key from (snapshot_slug, files_hash) to (snapshot_slug, scope_hash)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20251215000000"
down_revision = "20251214000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 0: Enable pgcrypto extension for SHA256 hashing
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Step 1: Add scope columns to examples table (nullable for migration)
    op.add_column("examples", sa.Column("scope_hash", sa.String(), nullable=True))
    op.add_column("examples", sa.Column("scope", pg.JSONB(), nullable=True))

    # Step 2: Populate scope JSONB from files column (convert to ExplicitFileScope)
    # Whole-snapshot examples: files=NULL → AllFilesScope {"kind": "entire_snapshot"}
    # Per-file examples: files=[...] → ExplicitFileScope {"kind": "specific_files", "files": [...]}
    op.execute("""
        UPDATE examples
        SET scope = CASE
            WHEN files IS NULL THEN '{"kind": "entire_snapshot"}'::jsonb
            ELSE jsonb_build_object('kind', 'specific_files', 'files', files)
        END
    """)

    # Step 3: Compute scope_hash as SHA256 of canonical JSON
    op.execute("""
        UPDATE examples
        SET scope_hash = encode(digest(scope::text, 'sha256'), 'hex')
    """)

    # Step 4: Make scope columns NOT NULL
    op.alter_column("examples", "scope_hash", nullable=False)
    op.alter_column("examples", "scope", nullable=False)

    # Step 5: Create unique index on (snapshot_slug, scope_hash)
    op.create_index("uq_examples_scope", "examples", ["snapshot_slug", "scope_hash"], unique=True)

    # Step 6: Add scope_hash to critic_runs (nullable for migration)
    op.add_column("critic_runs", sa.Column("scope_hash", sa.String(), nullable=True))

    # Step 7: Populate critic_runs.scope_hash from examples via files_hash join
    # Match critic_runs to examples using (snapshot_slug, files_hash)
    op.execute("""
        UPDATE critic_runs cr
        SET scope_hash = ex.scope_hash
        FROM examples ex
        WHERE cr.snapshot_slug = ex.snapshot_slug
          AND (
              (cr.files_hash IS NULL AND ex.files IS NULL) OR
              (cr.files_hash = ex.files_hash)
          )
    """)

    # Step 8: Make critic_runs.scope_hash NOT NULL
    op.alter_column("critic_runs", "scope_hash", nullable=False)

    # Step 9: Create index on critic_runs.scope_hash
    op.create_index("ix_critic_runs_scope_hash", "critic_runs", ["scope_hash"])

    # Step 10: Create FK from critic_runs to examples using scope_hash
    op.create_foreign_key(
        "critic_runs_scope_fkey",
        "critic_runs",
        "examples",
        ["snapshot_slug", "scope_hash"],
        ["snapshot_slug", "scope_hash"],
        ondelete="RESTRICT",
    )

    # Step 11: Drop views that depend on files/files_hash columns (must come before dropping columns)
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    # Step 12: Drop old files_hash FK and index from critic_runs (if they exist)
    op.execute("ALTER TABLE critic_runs DROP CONSTRAINT IF EXISTS critic_runs_files_fkey")
    op.drop_index("ix_critic_runs_files_hash", "critic_runs")

    # Step 13: Drop old files and files_hash columns from critic_runs
    op.drop_column("critic_runs", "files")
    op.drop_column("critic_runs", "files_hash")

    # Step 14: Drop old unique index on examples (snapshot_slug, files_hash)
    op.drop_index("uq_examples_file_set", "examples")

    # Step 15: Drop old files and files_hash columns from examples
    op.drop_column("examples", "files")
    op.drop_column("examples", "files_hash")

    # Step 16: Drop old is_whole_snapshot column from examples
    op.drop_column("examples", "is_whole_snapshot")


def downgrade() -> None:
    # Downgrade not implemented - lossy migration
    raise NotImplementedError("Downgrade not supported for scope architecture migration")
