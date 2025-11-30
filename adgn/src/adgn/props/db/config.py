"""Database configuration for production and test environments."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DatabaseConfig:
    """Database connection URLs for admin and agent users."""

    admin_url: str
    agent_url: str | None = None


# Default database URLs (can be overridden by environment variables)
# Note: admin_url expects postgres superuser for schema management (recreate_database, RLS policies)
_DEFAULT_PROD_ADMIN_URL = "postgresql://postgres:postgres@localhost:5433/eval_results"
_DEFAULT_PROD_AGENT_URL = "postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results"
_DEFAULT_TEST_ADMIN_URL = "postgresql://postgres:postgres@localhost:5433/eval_results_test"
_DEFAULT_TEST_AGENT_URL = "postgresql://agent_user:agent_password_changeme@localhost:5433/eval_results_test"


def get_production_config() -> DatabaseConfig:
    """Get production database configuration.

    Returns:
        DatabaseConfig with admin and agent URLs for production database.

    Environment variables (override defaults):
        PROPS_DB_URL: Admin user URL
        PROPS_AGENT_DB_URL: Agent user URL (read-only, RLS-restricted)
    """
    return DatabaseConfig(
        admin_url=os.environ.get("PROPS_DB_URL", _DEFAULT_PROD_ADMIN_URL),
        agent_url=os.environ.get("PROPS_AGENT_DB_URL", _DEFAULT_PROD_AGENT_URL),
    )


def get_test_config() -> DatabaseConfig:
    """Get test database configuration.

    Returns:
        DatabaseConfig with admin and agent URLs for test database.

    Environment variables (override defaults):
        PROPS_TEST_DB_URL: Admin user URL for tests
        PROPS_TEST_AGENT_DB_URL: Agent user URL for tests
    """
    return DatabaseConfig(
        admin_url=os.environ.get("PROPS_TEST_DB_URL", _DEFAULT_TEST_ADMIN_URL),
        agent_url=os.environ.get("PROPS_TEST_AGENT_DB_URL", _DEFAULT_TEST_AGENT_URL),
    )
