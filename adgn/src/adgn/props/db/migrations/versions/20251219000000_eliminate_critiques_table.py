"""Eliminate critiques table - use critic_runs directly.

Revision ID: 20251219000000
Revises: 20251214000000
Create Date: 2025-12-19 00:00:00.000000

Changes:
1. Change GraderRun.critique_id FK to critic_run_id FK
2. Drop critiques table (Critique ORM)
3. Update relationships

Rationale:
- Critiques were just wrappers for snapshot_slug + payload JSONB
- CriticRun already has snapshot_slug
- reported_issues table (keyed by critic_run_id) is the normalized source
- No need for intermediate Critique abstraction
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "20251219000000"
down_revision = "20251215000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Add new critic_run_id column (nullable initially for migration)
    op.add_column("grader_runs", sa.Column("critic_run_id", pg.UUID(as_uuid=True), nullable=True))

    # Step 2: Populate critic_run_id from critiques.critic_run_id
    # This assumes all critiques have an associated critic_run (no manual critiques)
    op.execute("""
        UPDATE grader_runs gr
        SET critic_run_id = (
            SELECT cr.id
            FROM critiques c
            JOIN critic_runs cr ON cr.critique_id = c.id
            WHERE c.id = gr.critique_id
        )
    """)

    # Step 3: Verify no NULL critic_run_ids (would indicate manual critiques)
    # If this fails, there are manual critiques that need to be handled
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM grader_runs WHERE critic_run_id IS NULL) THEN
                RAISE EXCEPTION 'Found grader_runs with manual critiques (no critic_run). These must be migrated or deleted.';
            END IF;
        END $$;
    """)

    # Step 4: Make critic_run_id NOT NULL and add FK
    op.alter_column("grader_runs", "critic_run_id", nullable=False)
    op.create_foreign_key(
        "grader_runs_critic_run_id_fkey", "grader_runs", "critic_runs", ["critic_run_id"], ["id"], ondelete="RESTRICT"
    )

    # Step 5: Drop views that depend on grader_runs.critique_id (must come before dropping column)
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_prompt CASCADE")
    op.execute("DROP VIEW IF EXISTS aggregated_recall_by_example CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_statistics CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_run_credits CASCADE")
    op.execute("DROP VIEW IF EXISTS occurrence_credits CASCADE")
    op.execute("DROP FUNCTION IF EXISTS get_validation_run_aggregates() CASCADE")

    # Step 6: Drop old critique_id column and FK
    op.drop_constraint("grader_runs_critique_id_fkey", "grader_runs", type_="foreignkey")
    op.drop_column("grader_runs", "critique_id")

    # Step 7: Drop CriticRun.critique_id (relationship is now reversed)
    op.drop_constraint("critic_runs_critique_id_fkey", "critic_runs", type_="foreignkey")
    op.drop_column("critic_runs", "critique_id")

    # Step 8: Drop critiques table
    op.drop_table("critiques")


def downgrade() -> None:
    # Recreate critiques table
    op.create_table(
        "critiques",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("snapshot_slug", sa.String(), sa.ForeignKey("snapshots.slug", ondelete="RESTRICT"), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False, comment="Critique payload (DB model)"),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Recreate CriticRun.critique_id
    op.add_column("critic_runs", sa.Column("critique_id", pg.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("critic_runs_critique_id_fkey", "critic_runs", "critiques", ["critique_id"], ["id"])

    # Recreate GraderRun.critique_id
    op.add_column("grader_runs", sa.Column("critique_id", pg.UUID(as_uuid=True), nullable=True))

    # Note: Full downgrade requires recreating Critique rows with payload from reported_issues
    # This is intentionally not implemented as it's a lossy migration
    # Manual intervention required if downgrade is needed
    op.execute("""
        DO $$
        BEGIN
            RAISE WARNING 'Downgrade is incomplete: critiques table recreated but data not migrated. Manual intervention required.';
        END $$;
    """)

    op.create_foreign_key("grader_runs_critique_id_fkey", "grader_runs", "critiques", ["critique_id"], ["id"])
    op.drop_constraint("grader_runs_critic_run_id_fkey", "grader_runs", type_="foreignkey")
    op.drop_column("grader_runs", "critic_run_id")
