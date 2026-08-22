"""Align the Kubernetes grant scope constraint with canonical scope JSON.

Only exact-namespace scopes serialize a ``namespaces`` field.  The other discriminated-union
variants serialize as ``{"kind": ...}``, so the original constraint rejected every valid
all-namespaces, cluster, and non-resource grant.

Revision ID: 0092
Revises: 0091
"""

from __future__ import annotations

from alembic import op

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: str | None = None
depends_on: str | None = None


_CONSTRAINT = "ck_kubernetes_grants_scope_shape"
_CANONICAL_SCOPE_SHAPE = (
    "jsonb_typeof(scope) = 'object' "
    "AND scope ? 'kind' "
    "AND scope->>'kind' IN ('namespaces', 'all_namespaces', 'cluster', 'non_resource') "
    "AND ((scope->>'kind' = 'namespaces' "
    "AND scope ? 'namespaces' "
    "AND jsonb_typeof(scope->'namespaces') = 'array' "
    "AND jsonb_array_length(scope->'namespaces') > 0) "
    "OR (scope->>'kind' <> 'namespaces' AND NOT (scope ? 'namespaces')))"
)
_LEGACY_SCOPE_SHAPE = (
    "jsonb_typeof(scope) = 'object' "
    "AND scope ? 'kind' AND scope ? 'namespaces' "
    "AND scope->>'kind' IN ('namespaces', 'all_namespaces', 'cluster', 'non_resource') "
    "AND jsonb_typeof(scope->'namespaces') = 'array' "
    "AND ((scope->>'kind' = 'namespaces' AND jsonb_array_length(scope->'namespaces') > 0) "
    "OR (scope->>'kind' <> 'namespaces' AND jsonb_array_length(scope->'namespaces') = 0))"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "kubernetes_grants", type_="check")
    op.create_check_constraint(_CONSTRAINT, "kubernetes_grants", _CANONICAL_SCOPE_SHAPE)


def downgrade() -> None:
    # Do not rewrite or discard canonical non-exact grants.  If any exist, restoring the legacy
    # constraint must fail closed because the old application cannot deserialize a synthetic
    # ``namespaces: []`` field on those discriminated-union variants.
    op.drop_constraint(_CONSTRAINT, "kubernetes_grants", type_="check")
    op.create_check_constraint(_CONSTRAINT, "kubernetes_grants", _LEGACY_SCOPE_SHAPE)
