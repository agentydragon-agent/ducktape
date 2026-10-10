"""Compare the squashed console baseline with the original chain's final schema.

This only uses the isolated pgvector testcontainer; it never reads a deployed DB.
"""

import hashlib
import re

import pytest_bazel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer

from haku.console.database_migrate import apply_migrations, sync_database_url
from util.testing.undeclared_outputs import undeclared_outputs_dir


def _schema(container: PostgresContainer, database: str) -> str:
    result = container.get_wrapped_container().exec_run(
        ["pg_dump", "-U", "postgres", "--schema-only", "--no-owner", "--exclude-table=public.alembic_version", database]
    )
    assert result.exit_code == 0, result.output.decode()
    # Random psql restriction keys are transport framing, not schema.
    return re.sub(r"^\\(?:un)?restrict .*\n", "", result.output.decode(), flags=re.MULTILINE)


def test_schema_baseline(postgres_container: PostgresContainer, db_url: str) -> None:
    apply_migrations(db_url)
    database = make_url(db_url).database
    assert database is not None
    before = _schema(postgres_container, database)
    (undeclared_outputs_dir() / "haku_console_schema.sql").write_text(before)
    # Original-chain CI capture; keep exact names, function bodies, policies and ACLs.
    canonical = "\n".join(
        line.rstrip() for line in before.splitlines() if line.strip() and not line.startswith(("--", "\\"))
    )
    assert (
        hashlib.sha256(canonical.encode()).hexdigest()
        == "d0590497f09e653f26f44871c3b792a375cb58afd600cad772cba7d4947b1eca"
    )
    engine = create_engine(sync_database_url(db_url))
    try:
        with engine.connect() as conn:
            revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
            objects = conn.execute(
                text("SELECT oid, relname FROM pg_class WHERE relnamespace = 'public'::regnamespace ORDER BY oid")
            ).all()
        assert revision == "0135"
        with engine.connect() as conn:
            assert conn.execute(text("SELECT index_id, index_type FROM recall_index.indexes")).all() == [
                ("haku-state", "git")
            ]
        apply_migrations(db_url)
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


if __name__ == "__main__":
    pytest_bazel.main()
