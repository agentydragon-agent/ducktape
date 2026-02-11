"""Production specimens validation.

Syncs the real specimens dataset (props/specimens/) into a testcontainer
PostgreSQL instance and validates data quality: split distribution, minimum
issue counts, and schema conformance (enforced by the sync code's Pydantic
models and DB constraints).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Generator
from pathlib import Path

import pytest
import pytest_bazel
from hamcrest import assert_that, greater_than_or_equal_to
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

from props.core.splits import Split
from props.db.config import DatabaseConfig
from props.db.database import Database
from props.db.models import Snapshot
from props.db.setup import ensure_database_exists
from props.db.sync.sync import sync_all
from test_util.image_loader import load_image
from third_party.containers.rlocations import POSTGRES_16_TARBALL, RYUK_TARBALL

pytestmark = pytest.mark.integration

SPECIMENS_PATH = Path(__file__).resolve().parent.parent / "specimens"


@pytest.fixture(scope="module")
def postgres_container() -> Generator[PostgresContainer]:
    """Module-scoped PostgreSQL testcontainer."""
    load_image(RYUK_TARBALL)
    load_image(POSTGRES_16_TARBALL)
    container = PostgresContainer(image="postgres:16", username="postgres", password="postgres", dbname="postgres")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="module")
def module_monkeypatch() -> Generator[pytest.MonkeyPatch]:
    """Module-scoped monkeypatch for environment variable overrides."""
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def synced_production_db(
    postgres_container: PostgresContainer, module_monkeypatch: pytest.MonkeyPatch
) -> Generator[Database]:
    """Module-scoped database synced with production specimens.

    Creates a testcontainer PostgreSQL, syncs all specimens from
    props/specimens/, and yields the Database for tests.
    """
    host = postgres_container.get_container_host_ip()
    port = int(postgres_container.get_exposed_port(5432))
    base_config = DatabaseConfig(host=host, port=port, database="postgres", user="postgres", password="postgres")

    db_name = "props_test_production_specimens"
    ensure_database_exists(base_config, db_name, drop_existing=True)
    test_config = base_config.with_database(db_name)

    postgres_config = base_config.with_database("postgres")
    postgres_engine = create_engine(postgres_config.url, isolation_level="AUTOCOMMIT")

    db = Database(test_config)
    db.recreate()

    module_monkeypatch.setenv("ADGN_PROPS_SPECIMENS_ROOT", str(SPECIMENS_PATH))
    with db.session() as session:
        sync_all(session, use_staged=True, collect_errors=True)

    yield db

    db.dispose()
    with postgres_engine.connect() as conn:
        conn.execute(
            text(f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{db_name}'
                  AND pid <> pg_backend_pid()
            """)
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    postgres_engine.dispose()


def test_sync_succeeds(synced_production_db: Database) -> None:
    """Verify that sync completes without errors.

    This is the primary validation — sync_all() parses all manifest.yaml and
    issues/*.yaml files through Pydantic models, enforces schema constraints,
    and populates the database. If this passes, the specimens data is valid.
    """
    with synced_production_db.session() as session:
        count = session.query(Snapshot).count()
    assert count > 0, "No snapshots were synced"


def test_split_distribution(synced_production_db: Database) -> None:
    """Verify train/valid/test split distribution meets minimum requirements."""

    with synced_production_db.session() as session:
        snapshots = session.query(Snapshot).all()

        specimen_counts: Counter[Split] = Counter()
        issue_counts: Counter[Split] = Counter()

        for snapshot in snapshots:
            specimen_counts[snapshot.split] += 1
            issue_counts[snapshot.split] += len(snapshot.true_positives)

    assert_that(specimen_counts[Split.TRAIN], greater_than_or_equal_to(1))
    assert_that(specimen_counts[Split.VALID], greater_than_or_equal_to(1))

    assert_that(issue_counts[Split.TRAIN], greater_than_or_equal_to(60))
    assert_that(issue_counts[Split.VALID], greater_than_or_equal_to(50))


if __name__ == "__main__":
    pytest_bazel.main()
