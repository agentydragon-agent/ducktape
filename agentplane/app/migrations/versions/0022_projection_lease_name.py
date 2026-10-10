"""Name the app projection lease for its current responsibility; preserve all rows."""

from alembic import op

revision = "0022_projection_lease_name"
down_revision = "0021_projected_feed_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical-revision replay tests can retain later schema changes.
    op.execute("ALTER TABLE IF EXISTS sandbox_ingestion RENAME TO sandbox_projection_lease")


def downgrade() -> None:
    op.rename_table("sandbox_projection_lease", "sandbox_ingestion")
