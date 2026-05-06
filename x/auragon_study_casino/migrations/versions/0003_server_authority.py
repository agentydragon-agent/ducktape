"""Add server-authoritative action log and snapshots.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("game_events", sa.Column("rules_version", sa.String(length=32), nullable=True))
    op.add_column("game_events", sa.Column("rng_version", sa.String(length=32), nullable=True))

    op.create_table(
        "ledger_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_action_id", sa.String(length=128), nullable=False),
        sa.Column("server_at_ms", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("rules_version", sa.String(length=32), nullable=False),
        sa.Column("rng_version", sa.String(length=32), nullable=True),
        sa.Column("credits_before", sa.Integer(), nullable=False),
        sa.Column("credits_after", sa.Integer(), nullable=False),
        sa.Column("tokens_before", sa.Integer(), nullable=False),
        sa.Column("tokens_after", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("client_action_id", name="ledger_events_client_action_id_unique"),
    )
    op.create_index("idx_ledger_events_server_at", "ledger_events", ["server_at_ms"])
    op.create_index("idx_ledger_events_action_type", "ledger_events", ["action_type"])

    op.create_table(
        "state_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_at_ms", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("doc_update_blob", sa.LargeBinary(), nullable=False),
        sa.Column("decoded_json", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("idx_state_snapshots_server_at", "state_snapshots", ["server_at_ms"])
    op.create_index("idx_state_snapshots_reason", "state_snapshots", ["reason"])

    op.create_table(
        "blackjack_hands",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("created_at_ms", sa.Integer(), nullable=False),
        sa.Column("updated_at_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("wager_credits", sa.Integer(), nullable=False),
        sa.Column("current_wager_credits", sa.Integer(), nullable=False),
        sa.Column("credits_before", sa.Integer(), nullable=False),
        sa.Column("tokens_before", sa.Integer(), nullable=False),
        sa.Column("shoe_json", sa.Text(), nullable=False),
        sa.Column("player_json", sa.Text(), nullable=False),
        sa.Column("dealer_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
    )
    op.create_index("idx_blackjack_hands_status", "blackjack_hands", ["status"])


def downgrade() -> None:
    op.drop_index("idx_blackjack_hands_status", table_name="blackjack_hands")
    op.drop_table("blackjack_hands")
    op.drop_index("idx_state_snapshots_reason", table_name="state_snapshots")
    op.drop_index("idx_state_snapshots_server_at", table_name="state_snapshots")
    op.drop_table("state_snapshots")
    op.drop_index("idx_ledger_events_action_type", table_name="ledger_events")
    op.drop_index("idx_ledger_events_server_at", table_name="ledger_events")
    op.drop_table("ledger_events")
    op.drop_column("game_events", "rng_version")
    op.drop_column("game_events", "rules_version")
