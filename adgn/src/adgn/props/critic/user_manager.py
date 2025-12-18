"""Temporary PostgreSQL user management for critic agents with RLS-scoped access.

Creates ephemeral database users for critic agents with access restricted to
specific critic runs via Row-Level Security policies.

The username pattern (critic_agent_{run_id}) encodes the run UUID, which the
RLS function current_critic_run_id() extracts to filter database access.

Critic agents have NO access to ground truth tables (true_positives, false_positives).
They can only write to their own reported_issues and reported_issue_occurrences tables.

Usage:
    async with CriticUserManager(admin_config, run_id) as creds:
        # Agent has scoped database access (write own issues, NO ground truth access)
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


class CriticUserManager(TempUserManager):
    """Temporary PostgreSQL user with RLS-scoped access to a critic run.

    The created user can write to reported_issues and reported_issue_occurrences
    (filtered to their run_id) but has NO access to ground truth tables.

    Username pattern: critic_agent_{run_id}
    The RLS function current_critic_run_id() extracts run_id from the username.

    RLS automatically filters queries to the specified critic run.
    NO DELETE privileges - only INSERT, SELECT, UPDATE (soft deletes via cancelled_at).
    """

    def __init__(self, admin_config: DbConnectionConfig, run_id: UUID):
        """Initialize critic user manager.

        Args:
            admin_config: Admin database connection (must have CREATE ROLE permission)
            run_id: Critic run UUID to scope access to
        """
        super().__init__(admin_config)
        self.run_id = run_id

    def generate_username(self) -> str:
        """Generate username encoding the critic run UUID."""
        return f"critic_agent_{self.run_id}"

    async def grant_permissions(self, username: str) -> None:
        """Grant critic-specific permissions via template role inheritance.

        The critic_agent_template role (created in migration) has:
        - INSERT, SELECT, UPDATE (NO DELETE) on reported_issues and reported_issue_occurrences
        - SELECT on critic_runs (required for FK validation)
        - NO access to ground truth tables (true_positives, false_positives)
        - Schema usage and sequence usage

        RLS policies (created in migration) automatically filter access to the user's run_id.
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            quoted_username = quote_ident(username)
            await conn.execute(text(f"GRANT critic_agent_template TO {quoted_username}"))

        logger.debug(f"Granted critic_agent_template to {username}")

    async def revoke_permissions(self, username: str) -> None:
        """No-op: DROP ROLE automatically removes role memberships and inherited privileges."""
