"""Temporary PostgreSQL user management for prompt optimizer with RLS-scoped access.

Creates ephemeral database users for prompt optimization runs with access restricted to
train split data via Row-Level Security policies.

The username pattern (prompt_optimizer_agent_{run_id}) encodes the run ID, which the
RLS function current_prompt_optimizer_run_id() extracts to filter database access.

Usage:
    async with PromptOptimizerUserManager(admin_config, run_id) as creds:
        # Agent has scoped database access (read-only train split)
        engine = create_engine(creds.url())
        ...
    # User automatically cleaned up on exit
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text

from adgn.props.db.config import DbConnectionConfig
from adgn.props.db.temp_user_manager import TempUserManager

logger = logging.getLogger(__name__)


class PromptOptimizerUserManager(TempUserManager):
    """Temporary PostgreSQL user with RLS-scoped access to train split.

    The created user can read snapshots, true_positives, false_positives, and examples,
    filtered to TRAIN split only via Row-Level Security.

    Username pattern: prompt_optimizer_agent_{run_id}
    The RLS function current_prompt_optimizer_run_id() extracts run_id from the username.

    RLS automatically filters queries to TRAIN split data.
    """

    def __init__(self, admin_config: DbConnectionConfig, run_id: UUID):
        """Initialize prompt optimizer user manager.

        Args:
            admin_config: Admin database connection (must have CREATE ROLE permission)
            run_id: Prompt optimization run ID to scope access to (from PromptOptimizationRun.id)
        """
        super().__init__(admin_config)
        self.run_id = run_id

    def generate_username(self) -> str:
        """Generate username encoding the prompt optimization run ID.

        Replaces hyphens with underscores since PostgreSQL role names cannot contain hyphens.
        """
        # Replace hyphens in UUID with underscores for valid PostgreSQL role name
        run_id_str = str(self.run_id).replace("-", "_")
        return f"prompt_optimizer_agent_{run_id_str}"

    async def grant_permissions(self, username: str) -> None:
        """Grant prompt-optimizer-specific permissions.

        Permissions:
        - Read-only on training data and evaluation results tables (TRAIN split only via RLS)
        - Read-only on aggregate views (inherit RLS filtering from underlying tables)
        - EXECUTE on validation aggregation function (VALID split aggregates only)
        - Schema usage

        RLS policies filter all tables to TRAIN split.
        Validation function provides per-run aggregate access to VALID split.
        """
        # All tables with RLS policies for prompt optimizer users (read-only, train split only)
        rls_filtered_tables = [
            "snapshots",
            "true_positives",
            "false_positives",
            "examples",
            "critic_runs",
            "critiques",
            "grader_runs",
            "events",
            "prompts",
        ]

        # Views that aggregate data from RLS-filtered tables
        # (inherit split filtering from underlying tables via RLS)
        aggregate_views = [
            "occurrence_credits",
            "occurrence_run_credits",
            "aggregated_recall_by_prompt",
            "aggregated_recall_by_example",
            "occurrence_statistics",
        ]

        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            # Grant schema access
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {username}"))

            # Grant read-only on all RLS-filtered tables
            for table in rls_filtered_tables:
                await conn.execute(text(f"GRANT SELECT ON TABLE {table} TO {username}"))

            # Grant read-only on aggregate views
            for view in aggregate_views:
                await conn.execute(text(f"GRANT SELECT ON {view} TO {username}"))

            # Grant EXECUTE on SECURITY DEFINER validation function
            await conn.execute(text(f"GRANT EXECUTE ON FUNCTION get_validation_run_aggregates() TO {username}"))

        logger.debug(f"Granted prompt optimizer permissions to {username}")

    async def revoke_permissions(self, username: str) -> None:
        """Revoke prompt-optimizer-specific permissions before dropping user.

        Revokes EXECUTE on validation function, then calls base implementation
        to revoke table/sequence/schema permissions.
        """
        if self.admin_engine is None:
            return

        async with self.admin_engine.begin() as conn:
            # Revoke function privilege first (prevents "dependent objects" error on role drop)
            await conn.execute(text(f"REVOKE ALL ON FUNCTION get_validation_run_aggregates() FROM {username}"))

        # Call base implementation to revoke table/sequence/schema permissions
        await super().revoke_permissions(username)
