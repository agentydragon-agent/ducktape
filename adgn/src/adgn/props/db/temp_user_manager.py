"""Base class for temporary PostgreSQL user management with async context manager pattern.

Provides lifecycle management (create, yield credentials, cleanup) for ephemeral database users.
Subclasses implement domain-specific permission grants via grant_permissions().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
import secrets

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from adgn.props.db.config import DbConnectionConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TempUserCredentials:
    """Credentials for a temporary database user.

    Contains only the credentials (username, password) created by the manager.
    Callers combine these with their own connection parameters (host, port, database)
    based on their context (e.g., Docker containers use different host than admin).
    """

    username: str
    password: str


class TempUserManager(ABC):
    """Base async context manager for temporary PostgreSQL users.

    Lifecycle:
    1. Generate username and secure password
    2. Create PostgreSQL role
    3. Grant permissions (subclass-specific)
    4. Yield credentials (username, password)
    5. Revoke permissions (subclass-specific cleanup)
    6. Terminate connections and drop role

    Subclasses must implement:
    - generate_username(): Return username encoding scope/purpose
    - grant_permissions(): Grant domain-specific permissions

    Subclasses may override:
    - revoke_permissions(): Custom cleanup (e.g., drop RLS policies)

    Usage:
        class MyUserManager(TempUserManager):
            def __init__(self, admin_config: DbConnectionConfig, run_id: int):
                super().__init__(admin_config)
                self.run_id = run_id

            def generate_username(self) -> str:
                return f"myapp_run_{self.run_id}_agent"

            async def grant_permissions(self, username: str) -> None:
                async with self.admin_engine.begin() as conn:
                    await conn.execute(text(f"GRANT SELECT ON TABLE foo TO {username}"))

        async with MyUserManager(admin_config, 42) as creds:
            # Combine credentials with your connection parameters
            config = DbConnectionConfig(
                host="host.docker.internal",  # Override for Docker context
                port=5432,
                database="mydb",
                user=creds.username,
                password=creds.password,
            )
            engine = create_engine(config.url())
    """

    def __init__(self, admin_config: DbConnectionConfig):
        """Initialize with admin database config.

        Args:
            admin_config: Admin database connection (must have CREATE ROLE permission)
        """
        self.admin_config = admin_config
        self.admin_engine: AsyncEngine | None = None
        self._username: str | None = None
        self._password: str | None = None

    @abstractmethod
    def generate_username(self) -> str:
        """Generate username encoding scope/purpose.

        Called once during __aenter__.

        Returns:
            Username for the temporary role (e.g., "myapp_run_42_agent")
        """

    @abstractmethod
    async def grant_permissions(self, username: str) -> None:
        """Grant domain-specific permissions to the user.

        Called after user creation, before yielding credentials.
        Use self.admin_engine for database operations.

        Args:
            username: Role name to grant permissions to

        Example:
            async with self.admin_engine.begin() as conn:
                await conn.execute(text(f"GRANT SELECT ON TABLE foo TO {username}"))
                await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {username}"))
        """

    async def revoke_permissions(self, username: str) -> None:
        """Revoke permissions (override for custom cleanup).

        Called during __aexit__ before dropping the user.
        Base implementation revokes all table/sequence/schema permissions.

        Args:
            username: Role name to revoke permissions from
        """
        if self.admin_engine is None:
            return

        async with self.admin_engine.begin() as conn:
            await conn.execute(text(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {username}"))
            await conn.execute(text(f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {username}"))
            await conn.execute(text(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {username}"))

    async def __aenter__(self) -> TempUserCredentials:
        """Create user and grant permissions, return credentials."""
        self._username = self.generate_username()
        self._password = secrets.token_urlsafe(32)

        logger.info(f"Creating temporary user: {self._username}")

        # Create admin engine
        admin_url = self.admin_config.url().replace("postgresql://", "postgresql+asyncpg://")
        self.admin_engine = create_async_engine(admin_url, echo=False)

        # Create user
        await self._create_user(self._username, self._password)

        # Grant permissions (subclass-specific)
        await self.grant_permissions(self._username)

        logger.info(f"Temporary user {self._username} ready")

        # Return credentials only (caller combines with their connection parameters)
        return TempUserCredentials(username=self._username, password=self._password)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Revoke permissions, terminate connections, drop user."""
        if self.admin_engine is None or self._username is None:
            return

        try:
            await self.revoke_permissions(self._username)
            await self._terminate_connections(self._username)
            await self._drop_user(self._username)
            logger.info(f"Temporary user {self._username} cleaned up")
        except Exception as e:
            logger.error(f"Failed to cleanup user {self._username}: {e}", exc_info=True)
        finally:
            await self.admin_engine.dispose()

    async def _create_user(self, username: str, password: str) -> None:
        """Create PostgreSQL role with LOGIN privilege (idempotent).

        Args:
            username: Role name to create
            password: Secure password for the role
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            # Check if role exists first
            result = await conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :username"), {"username": username}
            )
            role_exists = result.scalar() is not None

            if not role_exists:
                # Create role with password (escape single quotes)
                escaped_password = password.replace("'", "''")
                await conn.execute(text(f"CREATE ROLE {username} WITH LOGIN PASSWORD '{escaped_password}'"))
                logger.debug(f"Created role: {username}")
            else:
                logger.debug(f"Role {username} already exists")

    async def _terminate_connections(self, username: str) -> None:
        """Terminate all active connections for the user.

        Required before dropping the role.

        Args:
            username: Role name to terminate connections for
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE usename = :username
                      AND pid != pg_backend_pid()
                """
                ),
                {"username": username},
            )

        logger.debug(f"Terminated connections for {username}")

    async def _drop_user(self, username: str) -> None:
        """Drop PostgreSQL role.

        Args:
            username: Role name to drop
        """
        assert self.admin_engine is not None, "admin_engine not initialized"
        async with self.admin_engine.begin() as conn:
            await conn.execute(text(f"DROP ROLE IF EXISTS {username}"))

        logger.debug(f"Dropped user: {username}")
