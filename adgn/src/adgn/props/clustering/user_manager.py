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
        """Grant clustering-specific permissions via template role inheritance.

        The clustering_agent_template role (created in migration) has:
        - Read-write on clustering tables (clustering_runs, unknown_clusters, unknown_assignments)
        - Read-only on reference tables (snapshots, TPs, FPs, grader_runs, critic_runs,
          reported_issues, reported_issue_occurrences, grading_decisions, examples, prompts)
        - Read-only on aggregate views
        - Schema usage and sequence usage

        RLS policies (created in setup.py) automatically filter access to the user's run_id.
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            quoted_username = quote_ident(username)
            await conn.execute(text(f"GRANT clustering_agent_template TO {quoted_username}"))

        logger.debug(f"Granted clustering_agent_template to {username}")

    async def revoke_permissions(self, username: str) -> None:
        """No-op: DROP ROLE automatically removes role memberships and inherited privileges."""
