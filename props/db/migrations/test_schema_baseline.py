"""Capture the final migrated schema and prove upgrade-to-head is a no-op at head.

The schema-only artifact supplies the frozen baseline when squashing the chain.
Only a disposable testcontainer database is used; no deployed database is contacted.
"""

import re

import pytest_bazel
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

from props.db.config import DatabaseConfig
from props.db.setup import ensure_database_exists, upgrade_database
from util.testing.postgres import force_drop_database_sync
from util.testing.undeclared_outputs import undeclared_outputs_dir


def _schema(container: PostgresContainer, database: str) -> str:
    result = container.get_wrapped_container().exec_run(
        ["pg_dump", "-U", "postgres", "--schema-only", "--no-owner", "--exclude-table=public.alembic_version", database]
    )
    assert result.exit_code == 0, result.output.decode()
    # pg_dump 18 emits random psql restriction keys, which are not schema.
    return re.sub(r"^\\(?:un)?restrict .*\n", "", result.output.decode(), flags=re.MULTILINE)


def test_schema_baseline(postgres_container: PostgresContainer, postgres_base_config: DatabaseConfig) -> None:
    database = "props_schema_baseline"
    ensure_database_exists(postgres_base_config, database)
    engine = create_engine(postgres_base_config.with_database(database).url)
    try:
        upgrade_database(engine)
        before = _schema(postgres_container, database)
        (undeclared_outputs_dir() / "props_schema.sql").write_text(before)
        with engine.connect() as conn:
            revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
            objects = conn.execute(
                text("SELECT oid, relname FROM pg_class WHERE relnamespace = 'public'::regnamespace ORDER BY oid")
            ).all()
        assert revision == "20260926000000"
        upgrade_database(engine)
        assert _schema(postgres_container, database) == before
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT oid, relname FROM pg_class WHERE relnamespace = 'public'::regnamespace ORDER BY oid")
                ).all()
                == objects
            )
    finally:
        engine.dispose()
        force_drop_database_sync(postgres_base_config.with_database("postgres").url, database)


if __name__ == "__main__":
    pytest_bazel.main()
