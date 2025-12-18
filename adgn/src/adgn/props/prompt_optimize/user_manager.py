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
from adgn.props.db.temp_user_manager import TempUserManager, quote_ident

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

        Returns username with standard UUID format (hyphens, not underscores).
        PostgreSQL allows hyphens in quoted role names.
        """
        return f"prompt_optimizer_agent_{self.run_id}"

    async def grant_permissions(self, username: str) -> None:
        """Grant prompt-optimizer-specific permissions via template role inheritance.

        The prompt_optimizer_agent_template role (created in migration) has:
        - Read-only on training data tables (RLS filters to TRAIN split)
        - Read-only on aggregate views
        - EXECUTE on validation aggregation function (VALID split aggregates only)
        - Schema usage

        RLS policies filter all tables to TRAIN split.
        Validation function provides per-run aggregate access to VALID split.
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            quoted_username = quote_ident(username)
            await conn.execute(text(f"GRANT prompt_optimizer_agent_template TO {quoted_username}"))

        logger.debug(f"Granted prompt_optimizer_agent_template to {username}")

    async def revoke_permissions(self, username: str) -> None:
        """No-op: DROP ROLE automatically removes role memberships and inherited privileges."""
