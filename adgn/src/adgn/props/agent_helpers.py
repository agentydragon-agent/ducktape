"""Helpers for agents running inside the runtime container.

This module provides simple access to:
- Database ORM and query interface
- Environment configuration from container environment

Usage from within an agent (e.g., prompt optimizer):

    from adgn.props.agent_helpers import setup_agent_database
    from adgn.props.db import get_session
    from adgn.props.db.models import Snapshot, GraderRun

    setup_agent_database()  # One-time setup (reads env, initializes connection)

    # Query the database
    with get_session() as session:
        snapshots = session.query(Snapshot).filter_by(split='train').all()
        for snap in snapshots:
            print(f"{snap.slug}: {snap.source_commit}")
"""

from __future__ import annotations

import logging
import os

from adgn.props.db.config import DatabaseConfig
from adgn.props.db.session import init_db

logger = logging.getLogger(__name__)


def get_agent_database_config() -> DatabaseConfig:
    """Get database configuration for agent running in container.

    Reads from standard PostgreSQL environment variables that are passed from host to container.
    PGHOST is set to container name for Docker network access.

    Returns:
        DatabaseConfig with agent credentials (read-only access)

    Raises:
        ValueError: If required environment variables not set
    """
    host = os.environ.get("PGHOST")
    port = os.environ.get("PGPORT")
    database = os.environ.get("PGDATABASE")
    user = os.environ.get("PGUSER")
    password = os.environ.get("PGPASSWORD")

    missing = []
    if not host:
        missing.append("PGHOST")
    if not port:
        missing.append("PGPORT")
    if not database:
        missing.append("PGDATABASE")
    if not user:
        missing.append("PGUSER")
    if not password:
        missing.append("PGPASSWORD")

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "These should be passed from host to container."
        )

    # Type assertions after validation - all values are guaranteed to be non-None here
    assert host is not None
    assert port is not None
    assert database is not None
    assert user is not None
    assert password is not None

    # Return config with agent credentials (read-only)
    # Note: We set admin credentials to agent credentials since agents only get read-only access
    return DatabaseConfig(
        host=host,
        port=int(port),
        database=database,
        container_name=host,  # Container name is same as host in this context
        admin_user=user,  # Use agent user as "admin" in this context
        admin_password=password,
        agent_user=user,
        agent_password=password,
    )


def setup_agent_database() -> None:
    """Initialize database connection for agent with read-only access.

    Call once at agent startup to set up the connection pool.
    After calling this, use get_session() to query the database.

    Raises:
        ValueError: If required environment variables not set
        sqlalchemy.exc.OperationalError: If cannot connect to database
    """
    config = get_agent_database_config()
    logger.info(
        f"Initializing agent database connection: {config.agent.host}:{config.agent.port}/{config.agent.database} "
        f"(user: {config.agent.user})"
    )
    init_db(config)
    logger.info("Agent database connection initialized (read-only access)")
