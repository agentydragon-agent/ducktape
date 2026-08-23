"""Permit one approved ToolCall to create multiple exact Kubernetes grants.

The source ToolCall remains immutable provenance on every grant row. Removing its unique
constraint is only a cardinality change: no batch identity or lifecycle table is introduced.

Revision ID: 0094
Revises: 0093
"""

from __future__ import annotations

from alembic import op

revision: str = "0094"
down_revision: str | None = "0093"
branch_labels: str | None = None
depends_on: str | None = None


_CONSTRAINT = "uq_kubernetes_grants_source_tool_call"
_INDEX = "idx_kubernetes_grants_source_tool_call"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "kubernetes_grants", type_="unique")
    op.create_index(_INDEX, "kubernetes_grants", ["source_tool_call_id"])


def downgrade() -> None:
    # Deliberately fail closed if any source ToolCall has created multiple rows. A downgrade must
    # not delete or rewrite durable grant provenance merely to recover the legacy cardinality.
    op.drop_index(_INDEX, table_name="kubernetes_grants")
    op.create_unique_constraint(_CONSTRAINT, "kubernetes_grants", ["source_tool_call_id"])
