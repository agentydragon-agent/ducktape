"""Database configuration for production and test environments.

Database connection parameters are set by devenv.nix and must be present in the environment.
Tests construct their own DatabaseConfig with per-test database names.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DbConnectionConfig:
    """Single-user database connection configuration.

    Contains all fields needed for a PostgreSQL connection. Use this directly
    when you need to pass connection details to a specific context (e.g., Docker container).
    """

    host: str
    port: int
    user: str
    password: str
    database: str

    def url(self) -> str:
        """Construct PostgreSQL connection URL."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    def with_host(self, host: str, port: int | None = None) -> DbConnectionConfig:
        """Return a copy with different host (and optionally port)."""
        return DbConnectionConfig(
            host=host,
            port=port if port is not None else self.port,
            user=self.user,
            password=self.password,
            database=self.database,
        )

    def with_database(self, database: str) -> DbConnectionConfig:
        """Return a copy with different database name."""
        return DbConnectionConfig(
            host=self.host, port=self.port, user=self.user, password=self.password, database=database
        )


@dataclass(frozen=True)
class DatabaseConfig:
    """Full database configuration with admin and agent access.

    Stores raw configuration values from environment variables. The admin and agent
    connection configs are computed properties that construct DbConnectionConfig on demand.
    """

    # Connection parameters (shared between admin and agent)
    host: str
    port: int
    database: str
    container_name: str

    # Admin credentials
    admin_user: str
    admin_password: str

    # Agent credentials
    agent_user: str
    agent_password: str

    @property
    def admin(self) -> DbConnectionConfig:
        """Admin connection config (full privileges, host-side access)."""
        return DbConnectionConfig(
            host=self.host, port=self.port, user=self.admin_user, password=self.admin_password, database=self.database
        )

    @property
    def agent(self) -> DbConnectionConfig:
        """Agent connection config (restricted privileges, host-side access)."""
        return DbConnectionConfig(
            host=self.host, port=self.port, user=self.agent_user, password=self.agent_password, database=self.database
        )

    def admin_url(self) -> str:
        """Construct admin connection URL (host-side access)."""
        return self.admin.url()

    def agent_url(self) -> str:
        """Construct agent connection URL (host-side access)."""
        return self.agent.url()

    @property
    def agent_for_container(self) -> DbConnectionConfig:
        """Agent connection config for container-to-container access within Docker network.

        Uses container_name:5432 instead of host:port for Docker network routing.
        """
        return DbConnectionConfig(
            host=self.container_name,
            port=5432,
            user=self.agent_user,
            password=self.agent_password,
            database=self.database,
        )

    def with_database(self, database: str) -> DatabaseConfig:
        """Create a new config with a different database name."""
        return DatabaseConfig(
            host=self.host,
            port=self.port,
            database=database,
            container_name=self.container_name,
            admin_user=self.admin_user,
            admin_password=self.admin_password,
            agent_user=self.agent_user,
            agent_password=self.agent_password,
        )


def _get_required_env(name: str) -> str:
    """Get required environment variable or raise."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(
            f"{name} environment variable not set. Are you running from a devenv shell? Try: direnv allow && cd ."
        )
    return value


def get_production_config() -> DatabaseConfig:
    """Get production database configuration.

    Environment variables (set by devenv.nix):
        PROPS_DB_HOST: Database host
        PROPS_DB_PORT: Database port
        PROPS_DB_CONTAINER_NAME: Container name for Docker network access
        PROPS_DB_ADMIN_USER: Admin username
        PROPS_DB_ADMIN_PASSWORD: Admin password
        PROPS_DB_AGENT_USER: Agent username
        PROPS_DB_AGENT_PASSWORD: Agent password
        PROPS_DB_NAME: Database name

    Raises:
        ValueError: If any required env var not set (run from devenv shell)
    """
    return DatabaseConfig(
        host=_get_required_env("PROPS_DB_HOST"),
        port=int(_get_required_env("PROPS_DB_PORT")),
        database=_get_required_env("PROPS_DB_NAME"),
        container_name=_get_required_env("PROPS_DB_CONTAINER_NAME"),
        admin_user=_get_required_env("PROPS_DB_ADMIN_USER"),
        admin_password=_get_required_env("PROPS_DB_ADMIN_PASSWORD"),
        agent_user=_get_required_env("PROPS_DB_AGENT_USER"),
        agent_password=_get_required_env("PROPS_DB_AGENT_PASSWORD"),
    )
