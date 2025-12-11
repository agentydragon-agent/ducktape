"""Database session management.

This module uses process-global state (_engine, _SessionLocal) for the database connection.

Usage pattern:
    # Connect to database (once per process, or in test fixture)
    init_db()  # Defaults to production config from component env vars

    # Anywhere in code
    with get_session() as session:
        session.add(obj)
        # Commits on successful exit, rolls back on exception

    # One-time setup: recreate database from scratch
    init_db()
    recreate_database()

Limitations:
    - Cannot have multiple database connections in the same process
    - Call init_db() only once per process (tests can call multiple times to switch DBs)
    - Safe with pytest-xdist using --dist=loadscope (module-level isolation)
    - Not thread-safe during init_db() (don't call concurrently)

Design rationale:
    - Connection pooling: Single engine = efficient connection reuse
    - Simplicity: No dependency injection, works well for evaluation harness use case
    - Test-friendly: Module-scoped fixtures work correctly with loadscope
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from adgn.props.db import setup
from adgn.props.db.config import DatabaseConfig, get_production_config
from adgn.props.db.models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def dispose_db() -> None:
    """Dispose of the current database connection.

    This is needed when switching databases (e.g., between test databases).
    After calling this, init_db() can be called again.
    """
    global _engine, _SessionLocal  # noqa: PLW0603

    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionLocal = None


def init_db(config: DatabaseConfig | None = None) -> None:
    """Connect to database and verify connection (fail fast).

    Args:
        config: Database configuration (defaults to production config from env vars)

    Raises:
        ValueError: If config is None and required env vars not set (run from devenv shell)
        sqlalchemy.exc.OperationalError: If cannot connect to database within timeout
        RuntimeError: If database already initialized (should only be called once)
    """
    global _engine, _SessionLocal  # noqa: PLW0603

    # Enforce single initialization - if already initialized, this is a bug
    if _engine is not None:
        raise RuntimeError(
            "Database already initialized. init_db() should only be called once. "
            "If you need to switch databases (e.g., in tests), you must explicitly "
            "reinitialize by disposing the engine first or restructuring the code."
        )

    if config is None:
        config = get_production_config()

    url = config.admin_url()
    logger.info(f"Connecting to database: {config.admin.host}:{config.admin.port}/{config.admin.database}")
    # Connection pool sized for parallel evaluation (default max_parallelism=20 + overhead)
    # pool_size: number of connections kept open
    # max_overflow: additional connections beyond pool_size
    # Total concurrent connections: pool_size + max_overflow = 32
    _engine = create_engine(url, echo=False, pool_size=20, max_overflow=12)
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

    # Verify connection immediately
    check_connection(timeout_secs=2)


def check_connection(timeout_secs: int = 2) -> None:
    """Validate database connection (fail fast if DB not reachable).

    Args:
        timeout_secs: Connection timeout in seconds (default: 2)

    Raises:
        RuntimeError: If database not initialized (call init_db() first)
        sqlalchemy.exc.OperationalError: If cannot connect to database within timeout
    """
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    logger.debug(f"Validating database connection (timeout: {timeout_secs}s)...")
    # Create a temporary engine with connection timeout for quick validation
    # Use render_as_string to properly preserve credentials
    test_engine = create_engine(
        _engine.url.render_as_string(hide_password=False), echo=False, connect_args={"connect_timeout": timeout_secs}
    )
    try:
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.debug("Database connection validated")
    finally:
        test_engine.dispose()


def recreate_database() -> None:
    """Recreate database from scratch (drop all + create agent_user + schema + RLS).

    This is destructive: drops all existing tables, views, and policies.

    Must call init_db() first to establish connection as postgres superuser.

    Raises:
        RuntimeError: If database not initialized (call init_db() first)
    """
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    logger.info("Recreating database from scratch...")
    _drop_all()
    setup.create_agent_user(_engine)
    _create_schema()
    logger.info("Database recreation complete")


def _drop_all() -> None:
    """Drop all database objects by dropping and recreating the public schema."""
    if _engine is None:
        raise RuntimeError("Database not initialized.")

    # Check if any of our tables exist
    inspector = inspect(_engine)
    existing_tables = set(inspector.get_table_names())
    our_tables = {table.name for table in Base.metadata.tables.values()}

    if our_tables & existing_tables:
        logger.info("Dropping entire public schema and recreating...")
        with _engine.begin() as conn:
            # Drop and recreate public schema (drops everything: tables, views, functions, types, policies)
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            # Restore default permissions on schema
            conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        logger.info("Public schema dropped and recreated")
    else:
        logger.debug("No tables to drop")


def _grant_select_on_tables() -> None:
    """Grant SELECT permission to agent_user on all tables."""
    if _engine is None:
        raise RuntimeError("Database not initialized.")

    # Get all table names from our metadata
    table_names = [table.name for table in Base.metadata.tables.values()]

    if not table_names:
        logger.debug("No tables to grant permissions on")
        return

    with _engine.begin() as conn:
        for table_name in table_names:
            conn.execute(text(f"GRANT SELECT ON TABLE {table_name} TO agent_user"))

    logger.info(f"Granted SELECT permission on {len(table_names)} tables to agent_user")


def _create_schema() -> None:
    """Create tables (from ORM models) + RLS policies + views (idempotent)."""
    if _engine is None:
        raise RuntimeError("Database not initialized.")

    # Create tables from ORM models
    logger.info("Creating tables from ORM models...")
    Base.metadata.create_all(bind=_engine)

    # Grant SELECT permission to agent_user on all tables
    # (in case default privileges didn't work or tables already existed)
    _grant_select_on_tables()

    # Enable RLS and create policies
    setup.enable_rls(_engine)

    # Create views
    setup.create_views(_engine)

    logger.info("Schema creation complete")


@contextmanager
def get_session() -> Iterator[Session]:
    """Get a database session (context manager).

    Example:
        with get_session() as session:
            session.add(obj)
            session.commit()

    Raises:
        RuntimeError: If database not initialized (call init_db() first)
    """
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
