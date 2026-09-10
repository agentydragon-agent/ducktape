"""Store shared MCP OAuth linkage and short-lived PKCE flows in Postgres."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_mcp_server_linkage"
down_revision = "0012_action_push_subscription"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_server_linkage",
        sa.Column("server_id", sa.Text(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("server_url", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("token", postgresql.JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_by", sa.Text(), nullable=True),
    )
    op.create_table(
        "mcp_linkage_flow",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("state_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("verifier", sa.Text(), nullable=False),
        sa.Column("operator_principal", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("mcp_linkage_flow")
    op.drop_table("mcp_server_linkage")
