"""Serve the read model through the `api` schema.

PostgREST reads these views instead of the tables in `public`, so what a reader can see is this list
rather than whatever a role happens to be granted on `public`. A view runs with its owner's rights, so
a role granted SELECT on `api` needs no access to `public` at all.

Left out: `plaid_api_events` (the Plaid call log), and from `links` the `access_token_secret` (the name
of the Secret holding the Item's access token) and `transactions_cursor` (sync bookkeeping).

Privileges are not granted here. The roles that read `api` are declared by CloudNativePG in the cluster
config, which the tests of this package do not have, so their grants live beside them
(cluster/k8s/agents/plaid-mcp/db/api-grants.sql). That script creates the schema too if this has not
run yet, and sets default privileges, so the order of the two does not matter.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINKS_COLUMNS = (
    "item_id",
    "institution_id",
    "institution_name",
    "label",
    "products_requested",
    "products_authorized",
    "products_billed",
    "status",
    "transactions_update_status",
    "transaction_days_requested",
    "created_at",
    "updated_at",
    "last_synced_at",
)
# Served as they are, each with the table its columns are documented on (a view has no comments of
# its own to inherit).
_AS_IS = {
    "accounts": "accounts",
    "account_product_status": "account_product_status",
    "current_transactions": "transactions",
    "transactions": "transactions",
    "balance_snapshots": "balance_snapshots",
    "securities": "securities",
    "holding_snapshots": "holding_snapshots",
    "investment_transactions": "investment_transactions",
    "liability_credit_snapshots": "liability_credit_snapshots",
    "liability_mortgage_snapshots": "liability_mortgage_snapshots",
    "liability_student_snapshots": "liability_student_snapshots",
    "sync_runs": "sync_runs",
}


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _copy_comments(view: str, documented_on: str) -> None:
    """PostgREST serves comments as descriptions in its OpenAPI document; give the view the ones its
    source has."""
    bind = op.get_bind()
    described = bind.execute(
        sa.text("SELECT obj_description(to_regclass(:view), 'pg_class')"), {"view": f"public.{view}"}
    ).scalar()
    if described is not None:
        op.execute(f"COMMENT ON VIEW api.{view} IS {_literal(described)}")
    columns = bind.execute(
        sa.text(
            """
            SELECT v.attname, col_description(source.attrelid, source.attnum)
            FROM pg_attribute v
            JOIN pg_attribute source
              ON source.attrelid = to_regclass(:source) AND source.attname = v.attname AND NOT source.attisdropped
            WHERE v.attrelid = to_regclass(:view) AND v.attnum > 0 AND NOT v.attisdropped
            """
        ),
        {"view": f"api.{view}", "source": f"public.{documented_on}"},
    ).all()
    for column, comment in columns:
        if comment is not None:
            op.execute(f"COMMENT ON COLUMN api.{view}.{column} IS {_literal(comment)}")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS api")
    op.execute(f"CREATE VIEW api.links AS SELECT {', '.join(_LINKS_COLUMNS)} FROM public.links")
    _copy_comments("links", "links")
    for view, documented_on in _AS_IS.items():
        op.execute(f"CREATE VIEW api.{view} AS SELECT * FROM public.{view}")
        _copy_comments(view, documented_on)


def downgrade() -> None:
    for view in ("links", *_AS_IS):
        op.execute(f"DROP VIEW api.{view}")
    # Not CASCADE: anything else in the schema blocks the downgrade rather than vanishing with it.
    op.execute("DROP SCHEMA api")
