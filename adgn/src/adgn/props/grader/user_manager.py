"""Temporary PostgreSQL user management for grader agents with RLS-scoped access.

Creates ephemeral database users for grader agents with access restricted to
specific grader runs via Row-Level Security policies.

The username pattern (grader_agent_{run_id}) encodes the run UUID, which the
RLS function current_grader_run_id() extracts to filter database access.

Grader agents have read-only access to ground truth tables (true_positives, false_positives)
and input critiques, plus write access to their own grading_decisions table.

Usage:
    async with GraderUserManager(admin_config, run_id) as creds:
        # Agent has scoped database access (read ground truth, write grading decisions)
        engine = create_engine(creds.url())
        ...
    # User automatically cleaned up on exit
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text

from adgn.props.db.config import DbConnectionConfig
from adgn.props.db.temp_user_manager import TempUserManager, quote_ident

logger = logging.getLogger(__name__)


class GraderUserManager(TempUserManager):
    """Temporary PostgreSQL user with RLS-scoped access to a grader run.

    The created user can:
    - Read ground truth tables (true_positives, false_positives)
    - Read input critic run (critic_runs, reported_issues, reported_issue_occurrences tables)
    - Write to grading_decisions (filtered to their run_id)

    Username pattern: grader_agent_{run_id}
    The RLS function current_grader_run_id() extracts run_id from the username.

    RLS automatically filters grading_decisions queries to the specified grader run.
    Full DML privileges (INSERT, SELECT, UPDATE, DELETE) - hard deletes for decision revision.
    """

    def __init__(self, admin_config: DbConnectionConfig, run_id: UUID):
        """Initialize grader user manager.

        Args:
            admin_config: Admin database connection (must have CREATE ROLE permission)
            run_id: Grader run UUID to scope access to
        """
        super().__init__(admin_config)
        self.run_id = run_id

    def generate_username(self) -> str:
        """Generate username encoding the grader run UUID."""
        return f"grader_agent_{self.run_id}"

    async def grant_permissions(self, username: str) -> None:
        """Grant grader-specific permissions.

        Permissions:
        - SELECT on ground truth tables (true_positives, false_positives)
        - SELECT on critic input tables (critic_runs, reported_issues, reported_issue_occurrences)
        - SELECT on grading_credit_sums view (needed by check_credit_sum trigger)
        - INSERT, SELECT, UPDATE, DELETE on grading_decisions
        - Schema usage
        - Sequence usage for SERIAL columns

        RLS policies (created in migration) automatically filter grading_decisions to the user's run_id.
        Hard deletes enabled for decision revision workflow.
        """
        # Ground truth tables (read-only)
        ground_truth_tables = ["true_positives", "false_positives"]

        # Input tables (read-only) - critic output stored directly in critic_runs
        input_tables = ["critic_runs", "reported_issues", "reported_issue_occurrences"]

        # Views (read-only) - used by triggers for validation
        views = ["grading_credit_sums"]

        # Grader workflow tables (full DML: read-write with DELETE)
        grader_tables = ["grading_decisions"]

        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            quoted_username = quote_ident(username)

            # Grant schema access
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_username}"))

            # Grant SELECT on ground truth tables
            for table in ground_truth_tables:
                await conn.execute(text(f"GRANT SELECT ON TABLE {table} TO {quoted_username}"))

            # Grant SELECT on input tables
            for table in input_tables:
                await conn.execute(text(f"GRANT SELECT ON TABLE {table} TO {quoted_username}"))

            # Grant SELECT on views
            for view in views:
                await conn.execute(text(f"GRANT SELECT ON {view} TO {quoted_username}"))

            # Grant full DML (including DELETE) on grader tables
            for table in grader_tables:
                await conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {quoted_username}"))

            # Grant USAGE on sequences (needed for SERIAL columns in grading_decisions)
            await conn.execute(text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {quoted_username}"))

        logger.debug(f"Granted grader permissions to {username} (full DML, read ground truth + critiques + views)")
