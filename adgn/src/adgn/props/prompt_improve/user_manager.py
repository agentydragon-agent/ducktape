"""Temporary PostgreSQL user management with template role inheritance.

Creates ephemeral database users for improvement agents that inherit from
improvement_agent_template. RLS policies use functions to filter rows based on
allowed_examples stored in improvement_runs table.

Usage:
    async with ImprovementUserManager(admin_config, run_id, allowed_examples) as creds:
        # Run is registered automatically, agent has scoped database access via RLS
        engine = create_engine(creds.url())
        ...
    # User automatically cleaned up on exit
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text

from adgn.props.db.config import DbConnectionConfig
from adgn.props.db.temp_user_manager import TempUserCredentials, TempUserManager, quote_ident
from adgn.props.ids import SnapshotSlug
from adgn.props.prompt_improve.helpers import register_improvement_run

logger = logging.getLogger(__name__)


class ImprovementUserManager(TempUserManager):
    """Temporary PostgreSQL user that inherits from improvement_agent_template.

    Automatically registers the run in improvement_runs table before creating
    the temp user. RLS policies filter rows based on the username pattern
    (improvement_agent_{uuid}) which is used by current_improvement_run_id()
    to look up allowed_examples.
    """

    TEMPLATE_ROLE = "improvement_agent_template"

    def __init__(
        self, admin_config: DbConnectionConfig, run_id: UUID, allowed_examples: list[tuple[SnapshotSlug, str]]
    ):
        """Initialize improvement user manager.

        Args:
            admin_config: Admin database connection (must have CREATE ROLE permission)
            run_id: Unique identifier for this improvement run
            allowed_examples: List of (snapshot_slug, scope_hash) tuples the agent can access
        """
        super().__init__(admin_config)
        self.run_id = run_id
        self._allowed_examples = allowed_examples

    def generate_username(self) -> str:
        """Generate username with run ID.

        Format: improvement_agent_{uuid}
        Must match the pattern expected by current_improvement_run_id() function.
        """
        return f"improvement_agent_{self.run_id}"

    async def grant_permissions(self, username: str) -> None:
        """Grant template role to temp user.

        The template role (improvement_agent_template) has:
        - USAGE ON SCHEMA public
        - SELECT on tables: snapshots, true_positives, false_positives,
          examples, critic_runs, grader_runs, events

        RLS policies filter rows based on current_improvement_run_id() which
        extracts the run_id from the username and looks up allowed_examples
        in the improvement_runs table.
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            quoted = quote_ident(username)
            await conn.execute(text(f"GRANT {self.TEMPLATE_ROLE} TO {quoted}"))

        logger.debug(f"Granted {self.TEMPLATE_ROLE} to {username}")

    async def revoke_permissions(self, username: str) -> None:
        """No-op - DROP ROLE handles cleanup automatically.

        When the user is dropped, PostgreSQL automatically:
        - Revokes all privileges the role had (including inherited ones)
        - Removes role memberships

        No per-user policies to clean up since we use function-based RLS
        with improvement_runs table for allowed_examples lookup.
        """

    async def __aenter__(self) -> TempUserCredentials:
        """Register improvement run and create temp user.

        Registers the run in improvement_runs table BEFORE creating the user,
        so RLS policies can look up allowed_examples.
        """
        # Base class creates admin_engine in __aenter__, but we need it first
        # to register the run. Replicate the engine creation here.
        from sqlalchemy.ext.asyncio import create_async_engine

        admin_url = self.admin_config.url().replace("postgresql://", "postgresql+asyncpg://")
        self.admin_engine = create_async_engine(admin_url, echo=False)

        # Register run before creating user (RLS depends on this)
        async with self.admin_engine.begin() as conn:
            await register_improvement_run(conn, self.run_id, self._allowed_examples)
        logger.info(f"Registered improvement run {self.run_id} with {len(self._allowed_examples)} allowed examples")

        # Now create user via parent's logic (but skip engine creation since we did it)
        self._username = self.generate_username()
        self._password = __import__("secrets").token_urlsafe(32)

        logger.info(f"Creating temporary user: {self._username}")

        await self._create_user(self._username, self._password)
        await self.grant_permissions(self._username)

        logger.info(f"Temporary user {self._username} ready")

        return TempUserCredentials(username=self._username, password=self._password)
