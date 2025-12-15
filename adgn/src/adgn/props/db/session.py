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
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from adgn.props.db.config import DatabaseConfig, get_database_config
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
        config = get_database_config()

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
    """Recreate database from scratch (drop all + schema + RLS).

    This is destructive: drops all existing tables, views, and policies.
    Temporary database users are created per-agent as needed (not global roles).

    Must call init_db() first to establish connection as postgres superuser.

    Raises:
        RuntimeError: If database not initialized (call init_db() first)
    """
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    logger.info("Recreating database from scratch...")
    _drop_all()
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

    logger.debug(f"_drop_all: existing_tables={existing_tables}, our_tables={our_tables}")

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
        logger.debug("No tables to drop - schema is clean")


def _create_schema() -> None:
    """Create schema via Alembic migrations.

    Runs Alembic migrations to create tables, RLS policies, views, and grants.
    Used for test databases (production uses setup.py).
    """
    if _engine is None:
        raise RuntimeError("Database not initialized.")

    # Debug: Check what tables exist BEFORE running migrations
    inspector = inspect(_engine)
    existing_tables_before = set(inspector.get_table_names())
    logger.debug(f"_create_schema BEFORE migration: existing_tables={existing_tables_before}")

    # Check if alembic_version exists
    with _engine.connect() as conn:
        result = conn.execute(
            text("SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'alembic_version')")
        )
        has_alembic_before = result.scalar()
        logger.debug(f"_create_schema BEFORE migration: alembic_version exists={has_alembic_before}")

        if has_alembic_before:
            result = conn.execute(text("SELECT version_num FROM alembic_version"))
            version = result.scalar()
            logger.debug(f"_create_schema BEFORE migration: current revision={version}")

    # Run Alembic migrations to create all schema objects
    logger.info("Running Alembic migrations...")

    # Enable verbose Alembic logging
    logging.getLogger("alembic").setLevel(logging.DEBUG)

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))

    # Check what migrations exist
    migrations_dir = Path(__file__).parent / "migrations" / "versions"
    migration_files = list(migrations_dir.glob("*.py"))
    logger.debug(f"Found {len(migration_files)} migration files: {[f.name for f in migration_files]}")

    with _engine.begin() as conn:
        config.attributes["connection"] = conn

        # Check current revision BEFORE upgrade
        script = ScriptDirectory.from_config(config)
        context = MigrationContext.configure(conn)
        current_rev = context.get_current_revision()
        logger.debug(f"Current Alembic revision BEFORE upgrade: {current_rev}")
        logger.debug(f"Target revision (head): {script.get_current_head()}")

        command.upgrade(config, "head")

        # Check current revision AFTER upgrade
        context = MigrationContext.configure(conn)
        current_rev_after = context.get_current_revision()
        logger.debug(f"Current Alembic revision AFTER upgrade: {current_rev_after}")

    # Debug: Check what tables exist AFTER running migrations
    inspector = inspect(_engine)
    existing_tables_after = set(inspector.get_table_names())
    logger.debug(f"_create_schema AFTER migration: existing_tables={existing_tables_after}")

    logger.info("Schema creation complete (via migrations)")


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
