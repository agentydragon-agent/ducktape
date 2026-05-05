"""Add client-reported casino game event audit log.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_event_id", sa.String(length=128), nullable=False),
        sa.Column("server_at_ms", sa.Integer(), nullable=False),
        sa.Column("occurred_at_ms", sa.Integer(), nullable=False),
        sa.Column("game", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("wager_credits", sa.Integer(), nullable=False),
        sa.Column("payout_tokens", sa.Integer(), nullable=False),
        sa.Column("credits_before", sa.Integer(), nullable=False),
        sa.Column("credits_after", sa.Integer(), nullable=False),
        sa.Column("tokens_before", sa.Integer(), nullable=False),
        sa.Column("tokens_after", sa.Integer(), nullable=False),
        sa.Column("server_credits", sa.Integer(), nullable=False),
        sa.Column("server_tokens", sa.Integer(), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("client_event_id", name="game_events_client_event_id_unique"),
    )
    op.create_index("idx_game_events_server_at", "game_events", ["server_at_ms"])
    op.create_index("idx_game_events_game", "game_events", ["game"])


def downgrade() -> None:
    op.drop_index("idx_game_events_game", table_name="game_events")
    op.drop_index("idx_game_events_server_at", table_name="game_events")
    op.drop_table("game_events")
