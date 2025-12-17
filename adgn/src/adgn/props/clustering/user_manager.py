"""Temporary PostgreSQL user management for clustering agents with RLS-scoped access.

Creates ephemeral database users for clustering agents with access restricted to
specific clustering runs via Row-Level Security policies.

The username pattern (clustering_run_{run_id}_agent) encodes the run ID, which the
RLS function current_clustering_run_id() extracts to filter database access.

Usage:
    async with ClusteringUserManager(admin_config, run_id) as creds:
        # Agent has scoped database access (read-write clustering tables, read-only reference tables)
        engine = create_engine(creds.url())
        ...
    # User automatically cleaned up on exit
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from adgn.props.db.config import DbConnectionConfig
from adgn.props.db.temp_user_manager import TempUserManager, quote_ident

logger = logging.getLogger(__name__)


class ClusteringUserManager(TempUserManager):
    """Temporary PostgreSQL user with RLS-scoped access to a clustering run.

    The created user can read-write clustering tables (filtered to their run_id) and
    read reference tables (snapshots, TPs, FPs, grader_runs, critic_runs, reported_issues,
    reported_issue_occurrences, grading_decisions, examples, prompts).

    Username pattern: clustering_run_{run_id}_agent
    The RLS function current_clustering_run_id() extracts run_id from the username.

    RLS automatically filters queries to the specified clustering run.
    """

    def __init__(self, admin_config: DbConnectionConfig, run_id: int):
        """Initialize clustering user manager.

        Args:
            admin_config: Admin database connection (must have CREATE ROLE permission)
            run_id: Clustering run ID to scope access to
        """
        super().__init__(admin_config)
        self.run_id = run_id

    def generate_username(self) -> str:
        """Generate username encoding the clustering run ID."""
        return f"clustering_run_{self.run_id}_agent"

    async def grant_permissions(self, username: str) -> None:
        """Grant clustering-specific permissions.

        Permissions:
        - Read-write on clustering tables (clustering_runs, unknown_clusters, unknown_assignments)
        - Read-only on reference tables (snapshots, TPs, FPs, grader_runs, critic_runs,
          reported_issues, reported_issue_occurrences, grading_decisions, examples, prompts)
        - Read-only on aggregate views (for optional metrics queries)
        - Schema usage

        RLS policies (created in setup.py) automatically filter access to the user's run_id.
        """
        # Clustering tables (read-write)
        clustering_tables = ["clustering_runs", "unknown_clusters", "unknown_assignments"]

        # Reference tables (read-only)
        reference_tables = [
            "snapshots",
            "true_positives",
            "false_positives",
            "grader_runs",
            "critic_runs",
            "reported_issues",
            "reported_issue_occurrences",
            "grading_decisions",
            "examples",
            "prompts",
        ]

        # Aggregate views (read-only, optional for metrics queries)
        aggregate_views = [
            "occurrence_credits",
            "occurrence_run_credits",
            "aggregated_recall_by_prompt",
            "aggregated_recall_by_example",
        ]

        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            quoted_username = quote_ident(username)

            # Grant schema access
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_username}"))

            # Grant read-write on clustering tables
            for table in clustering_tables:
                await conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {quoted_username}"))

            # Grant read-only on reference tables
            for table in reference_tables:
                await conn.execute(text(f"GRANT SELECT ON TABLE {table} TO {quoted_username}"))

            # Grant read-only on aggregate views
            for view in aggregate_views:
                await conn.execute(text(f"GRANT SELECT ON {view} TO {quoted_username}"))

            # Grant USAGE on sequences (needed for SERIAL columns in clustering tables)
            await conn.execute(text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {quoted_username}"))

        logger.debug(f"Granted clustering permissions to {username}")
