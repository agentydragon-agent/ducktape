"""Separate canonical index text from model-specific embedding work.

``state_index.chunks`` predates lexical retrieval and is both the content store and vector cache:
a row appears only after an embedding request succeeds. That couples source ingestion to a remote
service and leaves no durable work record when it fails. This additive expansion introduces:

- ``lexical_chunks`` — canonical content-addressed chunk text, independent of model;
- ``embedding_jobs`` — a durable, leased request to derive one model vector from such a chunk.

The old vector table remains untouched for rolling compatibility. A following code release
backfills and dual-writes lexical chunks; no reader switches tables in this migration.

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "state_index"


def upgrade() -> None:
    op.create_table(
        "lexical_chunks",
        sa.Column("corpus", sa.Text(), nullable=False),
        sa.Column("content_sha", sa.Text(), nullable=False),
        sa.Column("chunker_key", sa.Text(), nullable=False),
        sa.Column("byte_start", sa.BigInteger(), nullable=False),
        sa.Column("byte_end", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("corpus", "content_sha", "chunker_key", "byte_start"),
        schema=SCHEMA,
    )
    op.create_table(
        "embedding_jobs",
        sa.Column("corpus", sa.Text(), nullable=False),
        sa.Column("content_sha", sa.Text(), nullable=False),
        sa.Column("chunker_key", sa.Text(), nullable=False),
        sa.Column("byte_start", sa.BigInteger(), nullable=False),
        sa.Column("model_key", sa.Text(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["corpus", "content_sha", "chunker_key", "byte_start"],
            [
                f"{SCHEMA}.lexical_chunks.corpus",
                f"{SCHEMA}.lexical_chunks.content_sha",
                f"{SCHEMA}.lexical_chunks.chunker_key",
                f"{SCHEMA}.lexical_chunks.byte_start",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("corpus", "content_sha", "chunker_key", "byte_start", "model_key"),
        schema=SCHEMA,
    )
    op.create_index("idx_embedding_jobs_ready", "embedding_jobs", ["available_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("idx_embedding_jobs_ready", table_name="embedding_jobs", schema=SCHEMA)
    op.drop_table("embedding_jobs", schema=SCHEMA)
    op.drop_table("lexical_chunks", schema=SCHEMA)
