"""Remove the redundant app runner locator after public-ID routing is deployed.

Stop old app replicas before upgrade: their ORM still selects/writes this column.
Sandbox Service's authoritative bindings and all public identities stay unchanged.
"""

from alembic import op

revision = "0023_drop_app_runner_locator"
down_revision = "0022_session_projection_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL removes the column's local unique constraint without CASCADE.
    # IF EXISTS permits historical-revision replay tests over the current schema.
    op.execute("ALTER TABLE event_log DROP COLUMN IF EXISTS session_id")


def downgrade() -> None:
    # Only roll back to the public-ID runtime (#9707), not legacy-locator readers.
    # The discarded private copy cannot be reconstructed here; service owns it.
    op.execute("ALTER TABLE event_log ADD COLUMN session_id text")
    op.execute("UPDATE event_log SET session_id = id::text")
    op.execute("ALTER TABLE event_log ALTER COLUMN session_id SET NOT NULL")
    op.create_unique_constraint("event_log_sandbox_session_id_key", "event_log", ["sandbox", "session_id"])
