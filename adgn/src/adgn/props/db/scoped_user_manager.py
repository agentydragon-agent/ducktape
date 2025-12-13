"""Temporary PostgreSQL user management with RLS-scoped access.

Creates ephemeral database users for improvement agents with access restricted to
specific training examples via Row-Level Security policies.

Usage:
    async with scoped_db_user(admin_config, run_id, allowed_examples) as agent_config:
        # Agent has scoped database access
        session = create_session(agent_config)
        ...
    # User and policies automatically cleaned up on exit
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import secrets
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from adgn.props.db.config import DbConnectionConfig

logger = logging.getLogger(__name__)


@asynccontextmanager
async def scoped_db_user(
    admin_config: DbConnectionConfig,
    run_id: UUID,
    allowed_examples: list[tuple[str, str]],  # [(snapshot_slug, files_hash), ...]
) -> AsyncIterator[DbConnectionConfig]:
    """Create temporary PostgreSQL user with RLS-scoped access.

    The created user can only read rows from specific training examples. This provides
    isolation for improvement agents analyzing subsets of the training data.

    Lifecycle:
    1. Create role: improve_agent_{run_id[:8]}
    2. Create RLS policies (scope to allowed_examples)
    3. Yield agent connection config
    4. Cleanup: DROP policies + DROP role

    Args:
        admin_config: Admin database connection (must have permission to CREATE ROLE)
        run_id: Unique identifier for this improvement run
        allowed_examples: List of (snapshot_slug, files_hash) tuples agent can access

    Yields:
        DbConnectionConfig for the scoped agent user

    Example:
        async with scoped_db_user(config.admin, run_id, examples) as agent_cfg:
            # Agent can only see data from 'examples'
            engine = create_engine(agent_cfg.url())
            with Session(engine) as session:
                # Queries automatically filtered by RLS
                runs = session.query(CriticRun).all()
    """
    if not allowed_examples:
        raise ValueError("allowed_examples must not be empty")

    # Generate secure username and password
    username = f"improve_agent_{str(run_id)[:8]}"
    password = secrets.token_urlsafe(32)

    logger.info(f"Creating scoped database user: {username} (for {len(allowed_examples)} examples)")

    # Create async engine for admin operations
    admin_url = admin_config.url().replace("postgresql://", "postgresql+asyncpg://")
    admin_engine = create_async_engine(admin_url, echo=False)

    try:
        # Create user and policies
        await _create_user(admin_engine, username, password)
        await _create_policies(admin_engine, username, allowed_examples)

        # Yield agent connection config
        agent_config = admin_config.with_host(admin_config.host, admin_config.port)
        agent_config = DbConnectionConfig(
            host=admin_config.host,
            port=admin_config.port,
            user=username,
            password=password,
            database=admin_config.database,
        )

        logger.info(f"Scoped user {username} ready (access to {len(allowed_examples)} examples)")
        yield agent_config

    finally:
        # Cleanup: drop policies and user
        try:
            await _drop_policies(admin_engine, username)
            await _drop_user(admin_engine, username)
            logger.info(f"Scoped user {username} cleaned up")
        except Exception as e:
            logger.error(f"Failed to cleanup user {username}: {e}", exc_info=True)
        finally:
            await admin_engine.dispose()


async def _create_user(engine, username: str, password: str) -> None:
    """Create PostgreSQL role with LOGIN privilege.

    Uses conditional logic for idempotent creation (skips if role exists).
    Note: Password must be embedded in SQL string as DO blocks don't support parameters.
    """
    async with engine.begin() as conn:
        # Check if role exists first
        result = await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :username"), {"username": username})
        role_exists = result.scalar() is not None

        if not role_exists:
            # Create role with password (escape single quotes in password)
            escaped_password = password.replace("'", "''")
            await conn.execute(text(f"CREATE ROLE {username} WITH LOGIN PASSWORD '{escaped_password}'"))

        # Grant schema access
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {username}"))

        # Grant SELECT on all tables (agent is read-only)
        # RLS policies will further restrict which rows are visible
        await conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {username}"))

    logger.debug(f"Created user: {username}")


async def _create_policies(engine, username: str, allowed_examples: list[tuple[str, str]]) -> None:
    """Create RLS policies to scope access to specific training examples.

    Policies filter tables by (snapshot_slug, files_hash) pairs. Different tables
    need different policy patterns based on their schema:

    - snapshots/true_positives/false_positives: Filter by snapshot_slug IN (...)
    - critic_runs: Filter by (snapshot_slug, files_hash) IN VALUES (...)
    - critiques: Filter by id IN (SELECT critique_id FROM critic_runs WHERE ...)
    - grader_runs: Filter by critique_id IN (SELECT id FROM critiques WHERE ...)
    - events: Filter via FK to critic_runs (transcript_id)

    Args:
        engine: SQLAlchemy engine (must be admin connection)
        username: Role name to create policies for
        allowed_examples: List of (snapshot_slug, files_hash) tuples
    """
    # Extract unique snapshot slugs for snapshot-only tables
    snapshot_slugs = sorted({slug for slug, _ in allowed_examples})
    snapshot_slug_list = ", ".join(f"'{slug}'" for slug in snapshot_slugs)

    # Build VALUES clause for (snapshot_slug, files_hash) pairs
    values_clause = ", ".join(f"('{slug}', '{hash_}')" for slug, hash_ in allowed_examples)

    # Policy definitions (table_name → USING clause)
    policies = {
        # Snapshot-level tables (no files_hash)
        "snapshots": f"(slug IN ({snapshot_slug_list}))",
        "true_positives": f"(snapshot_slug IN ({snapshot_slug_list}))",
        "false_positives": f"(snapshot_slug IN ({snapshot_slug_list}))",
        # Example-level tables with (snapshot_slug, files_hash)
        "examples": f"((snapshot_slug, files_hash) IN (VALUES {values_clause}))",
        "critic_runs": f"((snapshot_slug, files_hash) IN (VALUES {values_clause}))",
        # Critiques: filter by being referenced from allowed critic_runs
        "critiques": f"""(id IN (
            SELECT critique_id FROM critic_runs
            WHERE (snapshot_slug, files_hash) IN (VALUES {values_clause})
            AND critique_id IS NOT NULL
        ))""",
        # Grader runs: filter by critique_id being in allowed critiques
        "grader_runs": f"""(critique_id IN (
            SELECT critique_id FROM critic_runs
            WHERE (snapshot_slug, files_hash) IN (VALUES {values_clause})
            AND critique_id IS NOT NULL
        ))""",
        # Events: FK to critic_runs via transcript_id
        "events": f"""(transcript_id IN (
            SELECT transcript_id FROM critic_runs
            WHERE (snapshot_slug, files_hash) IN (VALUES {values_clause})
        ))""",
    }

    async with engine.begin() as conn:
        for table_name, using_clause in policies.items():
            policy_name = f"{username}_{table_name}"

            # Check if policy already exists
            result = await conn.execute(
                text(
                    "SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = :table AND policyname = :policy"
                ),
                {"table": table_name, "policy": policy_name},
            )
            exists = result.scalar() is not None

            if exists:
                logger.debug(f"Policy {policy_name} already exists on {table_name}, skipping")
                continue

            # Create policy
            policy_sql = f"CREATE POLICY {policy_name} ON {table_name} FOR SELECT TO {username} USING {using_clause}"
            await conn.execute(text(policy_sql))
            logger.debug(f"Created policy: {policy_name} on {table_name}")

    logger.info(f"Created {len(policies)} RLS policies for {username}")


async def _drop_policies(engine, username: str) -> None:
    """Drop all RLS policies created for this user.

    Policies are named {username}_{table_name}, so we can find them by prefix.
    """
    tables = [
        "snapshots",
        "true_positives",
        "false_positives",
        "examples",
        "critiques",
        "critic_runs",
        "grader_runs",
        "events",
    ]

    async with engine.begin() as conn:
        for table_name in tables:
            policy_name = f"{username}_{table_name}"
            await conn.execute(text(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}"))

    logger.debug(f"Dropped policies for {username}")


async def _drop_user(engine, username: str) -> None:
    """Drop PostgreSQL role.

    Revokes all privileges before dropping. PostgreSQL requires all dependencies
    to be removed first (policies are dropped in _drop_policies).
    """
    async with engine.begin() as conn:
        # Revoke all privileges to break dependencies
        await conn.execute(text(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {username}"))
        await conn.execute(text(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {username}"))

        # Now safe to drop the role
        await conn.execute(text(f"DROP ROLE IF EXISTS {username}"))

    logger.debug(f"Dropped user: {username}")
