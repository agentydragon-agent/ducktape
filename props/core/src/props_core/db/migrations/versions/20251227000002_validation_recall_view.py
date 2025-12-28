"""Add validation_recall_by_definition view for whole-repo mode.

Aggregates per-run validation metrics using stats_with_ci.
Inherits access control from get_validation_full_snapshot_aggregates().

Revision ID: 20251227000002
Revises: 20251227000001
Create Date: 2025-12-27
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251227000002"
down_revision = "20251227000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW validation_recall_by_definition AS
        SELECT
            critic_definition_id,
            critic_model,
            compute_stats_with_ci(array_agg(
                total_credit / NULLIF(n_occurrences, 0)
            )) AS recall_stats
        FROM get_validation_full_snapshot_aggregates()
        GROUP BY critic_definition_id, critic_model
    """)

    op.execute("""
        COMMENT ON VIEW validation_recall_by_definition IS
        'Aggregated validation recall by definition for whole-repo mode.
Uses stats_with_ci for mean and 95% CI bounds. Only accessible to whole-repo mode agents.
Access fields: (recall_stats).n, (recall_stats).mean, (recall_stats).lcb95, (recall_stats).ucb95'
    """)

    op.execute("GRANT SELECT ON TABLE validation_recall_by_definition TO agent_base")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS validation_recall_by_definition")
