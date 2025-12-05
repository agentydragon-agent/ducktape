"""Database configuration for production and test environments.

Database connection parameters are set by devenv.nix and must be present in the environment.
Tests construct their own DatabaseConfig with per-test database names.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DatabaseConfig:
    """Database connection parameters.

    Construct URLs on-demand via admin_url() and agent_url() methods.
    """

    host: str
    port: int
    admin_user: str
    admin_password: str
    agent_user: str
    agent_password: str
    database: str

    def admin_url(self) -> str:
        """Construct admin connection URL."""
        return f"postgresql://{self.admin_user}:{self.admin_password}@{self.host}:{self.port}/{self.database}"

    def agent_url(self) -> str:
        """Construct agent connection URL."""
        return f"postgresql://{self.agent_user}:{self.agent_password}@{self.host}:{self.port}/{self.database}"

    def with_database(self, database: str) -> DatabaseConfig:
        """Create a new config with a different database name."""
        return DatabaseConfig(
            host=self.host,
            port=self.port,
            admin_user=self.admin_user,
            admin_password=self.admin_password,
            agent_user=self.agent_user,
            agent_password=self.agent_password,
            database=database,
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
        admin_user=_get_required_env("PROPS_DB_ADMIN_USER"),
        admin_password=_get_required_env("PROPS_DB_ADMIN_PASSWORD"),
        agent_user=_get_required_env("PROPS_DB_AGENT_USER"),
        agent_password=_get_required_env("PROPS_DB_AGENT_PASSWORD"),
        database=_get_required_env("PROPS_DB_NAME"),
    )
