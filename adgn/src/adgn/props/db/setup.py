"""Database setup and initialization (RLS policies, views, agent user).

Extracted from session.py to separate concerns:
- session.py: Connection management (init_db, get_session)
- setup.py: Database schema and security setup (recreate_database, RLS, views)
"""

from __future__ import annotations

import logging

from sqlalchemy import DDL, Engine, inspect, text
import sqlalchemy.exc

from adgn.props.db.models import Base

logger = logging.getLogger(__name__)


def recreate_database(engine: Engine) -> None:
    """Recreate database from scratch (drop all + create agent_user + schema + RLS).

    This is destructive: drops all existing tables, views, and policies.

    Args:
        engine: SQLAlchemy engine (must be connected as postgres superuser)
    """
    logger.info("Recreating database from scratch...")
    _drop_all(engine)
    _create_agent_user(engine)
    _create_schema(engine)
    logger.info("Database recreation complete")


def _drop_all(engine: Engine) -> None:
    """Drop all database objects by dropping and recreating the public schema."""
    # Check if any of our tables exist
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    our_tables = {table.name for table in Base.metadata.tables.values()}

    if our_tables & existing_tables:
        logger.info("Dropping entire public schema and recreating...")
        with engine.begin() as conn:
            # Drop and recreate public schema (drops everything: tables, views, functions, types, policies)
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            # Restore default permissions on schema
            conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        logger.info("Public schema dropped and recreated")
    else:
        logger.debug("No tables to drop")


def _create_agent_user(engine: Engine) -> None:
    """Create agent_user role with read-only permissions (idempotent)."""
    logger.info("Creating agent_user role...")
    with engine.begin() as conn:
        # Create agent_user role (idempotent)
        conn.execute(
            text("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_user') THEN
                    CREATE ROLE agent_user WITH LOGIN PASSWORD 'agent_password_changeme';
                END IF;
            END$$;
        """)
        )

        # Grant read-only access to schema
        conn.execute(text("GRANT USAGE ON SCHEMA public TO agent_user"))

        # Try to set default privileges (requires elevated permissions)
        # If this fails, we'll grant explicitly on existing tables instead
        try:
            conn.execute(
                text("""
                ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
                    GRANT SELECT ON TABLES TO agent_user
            """)
            )
            logger.info("Default privileges configured for postgres role")
        except sqlalchemy.exc.ProgrammingError as e:
            if "permission denied" in str(e).lower():
                logger.warning(
                    "Could not set default privileges (requires superuser/owner). "
                    "Will grant permissions explicitly on existing tables instead."
                )
            else:
                raise

    logger.info("Agent user configured")


def _grant_select_on_tables(engine: Engine) -> None:
    """Grant SELECT permission to agent_user on all tables."""
    # Get all table names from our metadata
    table_names = [table.name for table in Base.metadata.tables.values()]

    if not table_names:
        logger.debug("No tables to grant permissions on")
        return

    with engine.begin() as conn:
        for table_name in table_names:
            conn.execute(text(f"GRANT SELECT ON TABLE {table_name} TO agent_user"))

    logger.info(f"Granted SELECT permission on {len(table_names)} tables to agent_user")


def _create_schema(engine: Engine) -> None:
    """Create tables (from ORM models) + RLS policies + views (idempotent)."""
    # Create tables from ORM models
    logger.info("Creating tables from ORM models...")
    Base.metadata.create_all(bind=engine)

    # Grant SELECT permission to agent_user on all tables
    # (in case default privileges didn't work or tables already existed)
    _grant_select_on_tables(engine)

    # Enable RLS and create policies
    _enable_rls(engine)

    # Create views
    _create_views(engine)

    logger.info("Schema creation complete")


def _enable_rls(engine: Engine) -> None:
    """Enable Row-Level Security policies (idempotent).

    Access control for agent_user:
    - Train split: Full detail access (critiques, critic_runs, grader_runs, events)
    - Valid split: Only aggregate metrics from grader_runs (no critique details or execution traces)
    - Test split: Completely hidden

    Postgres superuser bypasses RLS (table owner).
    """
    with engine.connect() as check_conn:
        result = check_conn.execute(text("SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public'"))
        existing_policies = {(row[0], row[1]) for row in result}

    # RLS-enabled tables
    rls_table_names = [
        "snapshots",
        "true_positives",
        "false_positives",
        "critiques",
        "critic_runs",
        "grader_runs",
        "events",
    ]
    rls_tables = {Base.metadata.tables[name] for name in rls_table_names}

    # Define agent access rules per table
    # Note: Cast string literals to split_enum type for enum column comparison
    agent_access_rules = {
        "snapshots": "FOR SELECT TO agent_user USING (true)",
        "true_positives": "FOR SELECT TO agent_user USING (snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train'::split_enum))",
        "false_positives": "FOR SELECT TO agent_user USING (snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train'::split_enum))",
        "critiques": "FOR SELECT TO agent_user USING (snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train'::split_enum))",
        "critic_runs": "FOR SELECT TO agent_user USING (snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train'::split_enum))",
        "grader_runs": "FOR SELECT TO agent_user USING (snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train'::split_enum))",
        "events": "FOR SELECT TO agent_user USING (transcript_id IN (SELECT transcript_id FROM critic_runs WHERE snapshot_slug IN (SELECT slug FROM snapshots WHERE split = 'train'::split_enum)))",
    }

    with engine.begin() as conn:
        # Enable RLS on tables
        for table in rls_tables:
            conn.execute(DDL(f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY"))
            conn.execute(DDL(f"ALTER TABLE {table.name} FORCE ROW LEVEL SECURITY"))

        # Create agent policies (skip if exist)
        policies_created = 0
        for table_name in rls_table_names:
            policy_name = f"agent_{table_name}_policy"
            if (table_name, policy_name) not in existing_policies:
                conn.execute(DDL(f"CREATE POLICY {policy_name} ON {table_name} {agent_access_rules[table_name]}"))
                policies_created += 1
                logger.debug("Created policy: %s on %s", policy_name, table_name)
            else:
                logger.debug("Skipping existing policy: %s on %s", policy_name, table_name)

    logger.info(
        "RLS enabled: %d policies created, %d already exist", policies_created, len(rls_table_names) - policies_created
    )


def _create_views(engine: Engine) -> None:
    """Create database views (idempotent).

    Note: run_costs view is created automatically via DDL event listener in models.py
    """
    with engine.begin() as conn:
        # Drop old view name if it exists (migration)
        conn.execute(DDL("DROP VIEW IF EXISTS valid_grader_metrics"))

        # Drop and recreate valid_full_specimen_grader_metrics view
        conn.execute(DDL("DROP VIEW IF EXISTS valid_full_specimen_grader_metrics"))
        conn.execute(
            DDL(
                """
                CREATE VIEW valid_full_specimen_grader_metrics AS
                SELECT
                    g.snapshot_slug,
                    (g.output->'grade'->>'recall')::float as recall,
                    (g.output->'grade'->>'precision')::float as precision,
                    (g.output->'grade'->'metrics'->>'true_positives')::int as tp,
                    (g.output->'grade'->'metrics'->>'false_positives')::int as fp,
                    (g.output->'grade'->'metrics'->>'false_negatives')::int as fn,
                    g.model,
                    g.created_at
                FROM grader_runs g
                JOIN snapshots s ON g.snapshot_slug = s.slug
                WHERE s.split = 'valid'::split_enum
                """
            )
        )

        # Grant SELECT on views to agent_user
        conn.execute(text("GRANT SELECT ON valid_full_specimen_grader_metrics TO agent_user"))
        conn.execute(text("GRANT SELECT ON run_costs TO agent_user"))

    logger.info("Views created")
