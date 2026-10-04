"""Provider-neutral inbox identities and a durable GitHub ingress journal."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_github"
down_revision = "0004_source_union"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("inbox", "subscription"):
        op.alter_column(table, "next_poll", new_column_name="next_attempt", nullable=True)
    op.execute("ALTER INDEX ix_inbox_next_poll RENAME TO ix_inbox_next_attempt")
    op.add_column("subscription", sa.Column("generation", sa.BigInteger(), nullable=False, server_default="0"))
    op.alter_column("subscription", "generation", server_default=None)
    op.alter_column("subscription", "after_sequence", new_column_name="position")
    op.add_column("subscription", sa.Column("binding", postgresql.JSONB(), nullable=True))
    op.drop_column("subscription", "request_id")
    op.add_column("entry", sa.Column("event", postgresql.JSONB(), nullable=True))
    op.execute(
        "UPDATE entry SET event = jsonb_build_object('provider', 'actions', "
        "'request_id', request_id::text, 'sequence', source_sequence)"
    )
    op.alter_column("entry", "event", nullable=False)
    op.drop_constraint("entry_inbox_id_request_id_source_sequence_key", "entry", type_="unique")
    op.create_unique_constraint("entry_inbox_id_event_key", "entry", ["inbox_id", "event"])
    op.drop_column("entry", "request_id")
    op.drop_column("entry", "source_sequence")
    op.create_table(
        "github_delivery",
        sa.Column("position", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("app_id", sa.BigInteger(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("digest", sa.LargeBinary(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("app_id", "delivery_id"),
    )
    op.create_index("ix_github_delivery_repository_id", "github_delivery", ["repository_id"])


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM github_delivery) OR EXISTS "
                "(SELECT 1 FROM subscription WHERE creation #>> '{source,provider}' <> 'actions')"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Cannot downgrade while GitHub data exists; refusing data loss")
    for table in ("inbox", "subscription"):
        op.execute(f"UPDATE {table} SET next_attempt = now() WHERE next_attempt IS NULL")
        op.alter_column(table, "next_attempt", new_column_name="next_poll", nullable=False)
    op.execute("ALTER INDEX ix_inbox_next_attempt RENAME TO ix_inbox_next_poll")
    op.drop_column("subscription", "generation")
    op.drop_table("github_delivery")
    op.add_column("entry", sa.Column("request_id", sa.Uuid(), nullable=True))
    op.add_column("entry", sa.Column("source_sequence", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE entry SET request_id = (event ->> 'request_id')::uuid, source_sequence = (event ->> 'sequence')::bigint"
    )
    op.alter_column("entry", "request_id", nullable=False)
    op.alter_column("entry", "source_sequence", nullable=False)
    op.drop_constraint("entry_inbox_id_event_key", "entry", type_="unique")
    op.create_unique_constraint(
        "entry_inbox_id_request_id_source_sequence_key", "entry", ["inbox_id", "request_id", "source_sequence"]
    )
    op.drop_column("entry", "event")
    op.add_column("subscription", sa.Column("request_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE subscription SET request_id = (creation #>> '{source,request_id}')::uuid")
    op.alter_column("subscription", "request_id", nullable=False)
    op.drop_column("subscription", "binding")
    op.alter_column("subscription", "position", new_column_name="after_sequence")
