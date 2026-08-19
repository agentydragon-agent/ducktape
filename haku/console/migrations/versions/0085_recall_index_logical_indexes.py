"""Give every recall occurrence a durable logical index.

The physical schema became ``recall_index`` in 0083.  This migration makes the boundary real:
content and vectors remain globally deduplicated, while source occurrences, revision state, and
chat windows all name one logical index.  That is the boundary a later reader role/RLS policy can
enforce without trusting a query to remember a filter.

The two existing corpora are seeded as internal compatibility registrations so the current console
keeps its established behaviour.  This does not grant an additional caller access to either one;
the actor-bound public API arrives separately.

Revision ID: 0085
Revises: 0084
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "recall_index"
_HAKU_STATE = "haku-state"
_CONVERSATIONS = "haku-conversations"


def _table(name: str) -> str:
    return f"{SCHEMA}.{name}"


def upgrade() -> None:
    op.create_table(
        "indexes",
        sa.Column("index_id", sa.Text(), nullable=False),
        sa.Column("index_type", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("index_id", name="indexes_pkey"),
        sa.CheckConstraint("index_type IN ('git', 'chat')", name="ck_indexes_index_type"),
        schema=SCHEMA,
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_table("indexes")} (index_id, index_type)
            VALUES ('{_HAKU_STATE}', 'git'), ('{_CONVERSATIONS}', 'chat')
            """
        )
    )

    for table in ("git_chunks", "git_tip", "git_sync_state", "chat_chunks", "chat_chunk_messages", "chat_sessions"):
        op.add_column(table, sa.Column("index_id", sa.Text(), nullable=True), schema=SCHEMA)
    op.execute(f"UPDATE {_table('git_chunks')} SET index_id = '{_HAKU_STATE}'")
    op.execute(f"UPDATE {_table('git_tip')} SET index_id = '{_HAKU_STATE}'")
    op.execute(f"UPDATE {_table('git_sync_state')} SET index_id = '{_HAKU_STATE}'")
    for table in ("chat_chunks", "chat_chunk_messages", "chat_sessions"):
        op.execute(f"UPDATE {_table(table)} SET index_id = '{_CONVERSATIONS}'")
    for table in ("git_chunks", "git_tip", "git_sync_state", "chat_chunks", "chat_chunk_messages", "chat_sessions"):
        op.alter_column(table, "index_id", nullable=False, schema=SCHEMA)

    op.drop_constraint("git_chunks_pkey", "git_chunks", schema=SCHEMA, type_="primary")
    op.create_primary_key(
        "git_chunks_pkey", "git_chunks", ["index_id", "blob_sha", "chunker_key", "byte_start"], schema=SCHEMA
    )
    op.drop_constraint("git_tip_pkey", "git_tip", schema=SCHEMA, type_="primary")
    op.create_primary_key("git_tip_pkey", "git_tip", ["index_id", "path"], schema=SCHEMA)

    op.drop_constraint("git_sync_state_pkey", "git_sync_state", schema=SCHEMA, type_="primary")
    op.drop_constraint("ck_git_sync_state_singleton", "git_sync_state", schema=SCHEMA, type_="check")
    op.drop_column("git_sync_state", "id", schema=SCHEMA)
    op.create_primary_key("git_sync_state_pkey", "git_sync_state", ["index_id"], schema=SCHEMA)

    op.drop_constraint(
        "chat_chunk_messages_session_id_window_no_fkey", "chat_chunk_messages", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint("chat_chunks_pkey", "chat_chunks", schema=SCHEMA, type_="primary")
    op.create_primary_key("chat_chunks_pkey", "chat_chunks", ["index_id", "session_id", "window_no"], schema=SCHEMA)
    op.drop_constraint("chat_chunk_messages_pkey", "chat_chunk_messages", schema=SCHEMA, type_="primary")
    op.create_primary_key(
        "chat_chunk_messages_pkey",
        "chat_chunk_messages",
        ["index_id", "session_id", "window_no", "ordinal"],
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "chat_chunk_messages_index_id_session_id_window_no_fkey",
        "chat_chunk_messages",
        "chat_chunks",
        ["index_id", "session_id", "window_no"],
        ["index_id", "session_id", "window_no"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
    op.drop_constraint("chat_sessions_pkey", "chat_sessions", schema=SCHEMA, type_="primary")
    op.create_primary_key("chat_sessions_pkey", "chat_sessions", ["index_id", "session_id"], schema=SCHEMA)

    for table in ("git_chunks", "git_tip", "git_sync_state", "chat_chunks", "chat_sessions"):
        op.create_foreign_key(
            f"{table}_index_id_fkey",
            table,
            "indexes",
            ["index_id"],
            ["index_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
        )


def downgrade() -> None:
    """Only the two compatibility indexes can be collapsed back into the old singleton tables."""
    op.execute(
        sa.text(
            f"""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM {_table("indexes")}
                    WHERE index_id NOT IN ('{_HAKU_STATE}', '{_CONVERSATIONS}')
                ) THEN
                    RAISE EXCEPTION 'cannot downgrade recall indexes after additional indexes exist';
                END IF;
            END $$;
            """
        )
    )
    for table in ("git_chunks", "git_tip", "git_sync_state", "chat_chunks", "chat_sessions"):
        op.drop_constraint(f"{table}_index_id_fkey", table, schema=SCHEMA, type_="foreignkey")
    op.drop_constraint(
        "chat_chunk_messages_index_id_session_id_window_no_fkey",
        "chat_chunk_messages",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint("chat_chunk_messages_pkey", "chat_chunk_messages", schema=SCHEMA, type_="primary")
    op.create_primary_key(
        "chat_chunk_messages_pkey", "chat_chunk_messages", ["session_id", "window_no", "ordinal"], schema=SCHEMA
    )
    op.drop_constraint("chat_chunks_pkey", "chat_chunks", schema=SCHEMA, type_="primary")
    op.create_primary_key("chat_chunks_pkey", "chat_chunks", ["session_id", "window_no"], schema=SCHEMA)
    op.create_foreign_key(
        "chat_chunk_messages_session_id_window_no_fkey",
        "chat_chunk_messages",
        "chat_chunks",
        ["session_id", "window_no"],
        ["session_id", "window_no"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
    op.drop_constraint("chat_sessions_pkey", "chat_sessions", schema=SCHEMA, type_="primary")
    op.create_primary_key("chat_sessions_pkey", "chat_sessions", ["session_id"], schema=SCHEMA)

    op.drop_constraint("git_sync_state_pkey", "git_sync_state", schema=SCHEMA, type_="primary")
    op.add_column("git_sync_state", sa.Column("id", sa.SmallInteger(), nullable=True), schema=SCHEMA)
    op.execute(f"UPDATE {_table('git_sync_state')} SET id = 1")
    op.alter_column("git_sync_state", "id", nullable=False, schema=SCHEMA)
    op.create_primary_key("git_sync_state_pkey", "git_sync_state", ["id"], schema=SCHEMA)
    op.create_check_constraint("ck_git_sync_state_singleton", "git_sync_state", "id = 1", schema=SCHEMA)

    op.drop_constraint("git_tip_pkey", "git_tip", schema=SCHEMA, type_="primary")
    op.create_primary_key("git_tip_pkey", "git_tip", ["path"], schema=SCHEMA)
    op.drop_constraint("git_chunks_pkey", "git_chunks", schema=SCHEMA, type_="primary")
    op.create_primary_key("git_chunks_pkey", "git_chunks", ["blob_sha", "chunker_key", "byte_start"], schema=SCHEMA)
    for table in ("git_chunks", "git_tip", "git_sync_state", "chat_chunks", "chat_chunk_messages", "chat_sessions"):
        op.drop_column(table, "index_id", schema=SCHEMA)
    op.drop_table("indexes", schema=SCHEMA)
