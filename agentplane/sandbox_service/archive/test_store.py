"""Real PostgreSQL exercises transactional history, including independent replay."""

from collections.abc import AsyncIterator, Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from agentplane.protocol import event_log_pb2
from agentplane.sandbox_service.archive.database_migrate import RUNNER
from agentplane.sandbox_service.archive.store import ArchiveConflict, ArchiveNotFound, Store
from util.testing.postgres import create_database_sync, force_drop_database_sync
from util.testing.postgres_fixtures import postgres_container

# gazelle:include_dep @pypi//asyncpg
# gazelle:include_dep @pypi//psycopg


@pytest.fixture
def db_url(postgres_container: PostgresContainer) -> Iterator[str]:
    admin = f"postgresql+psycopg://postgres:postgres@{postgres_container.get_container_host_ip()}:{postgres_container.get_exposed_port(5432)}/postgres"
    name = f"archive_{uuid4().hex}"
    url = (
        make_url(create_database_sync(admin, name))
        .set(drivername="postgresql+asyncpg")
        .render_as_string(hide_password=False)
    )
    RUNNER.apply(url)
    yield url
    force_drop_database_sync(admin, name)


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_url)
    try:
        yield engine
    finally:
        await engine.dispose()


def entry(cursor: int, source: str = "source", *, resumed: bool = False) -> event_log_pb2.EventEntry:
    result = event_log_pb2.EventEntry(cursor=cursor)
    result.origin.source_id = source
    result.origin.sequence = cursor
    result.event.harness_started.resumed = resumed
    return result


async def opened(store: Store, session_id: UUID) -> None:
    await store.open(
        session_id, sandbox_namespace="testing", sandbox_name="gone",
        sandbox_uid=None, runner_session_id="original-native-path",
    )


@pytest.mark.asyncio
async def test_replay_survives_new_store_and_deleted_sandbox(engine: AsyncEngine) -> None:
    session_id = uuid4()
    store = Store(engine)
    await opened(store, session_id)
    await opened(store, session_id)
    assert await store.append(session_id, [entry(1), entry(2, resumed=True)]) == 2
    assert await Store(engine).append(session_id, [entry(1), entry(2, resumed=True), entry(3)]) == 3
    high_water, events = await Store(engine).read(session_id, after_cursor=1, limit=2)
    assert high_water == 3
    assert events == [entry(2, resumed=True), entry(3)]
    assert await Store(engine).read(session_id, after_cursor=3) == (3, [])
    with pytest.raises(ValueError, match="beyond"):
        await store.read(session_id, after_cursor=4)


@pytest.mark.asyncio
async def test_bad_batch_rolls_back_and_conflicting_duplicate_rejected(engine: AsyncEngine) -> None:
    store = Store(engine)
    session_id = uuid4()
    await opened(store, session_id)
    with pytest.raises(ArchiveConflict, match="expected 2"):
        await store.append(session_id, [entry(1), entry(3)])
    assert await store.read(session_id) == (0, [])
    assert await store.append(session_id, [entry(1), entry(2)]) == 2
    for bad in ([entry(2, resumed=True)], [entry(3, "other")], [entry(4)]):
        with pytest.raises(ArchiveConflict):
            await store.append(session_id, bad)
    assert await store.read(session_id) == (2, [entry(1), entry(2)])
    with pytest.raises(ArchiveConflict, match="locator"):
        await store.open(session_id, sandbox_namespace="testing", sandbox_name="new",
                         sandbox_uid=None, runner_session_id="original-native-path")
    with pytest.raises(ArchiveNotFound):
        await store.append(uuid4(), [entry(1)])


@pytest.mark.asyncio
async def test_two_replica_writers_serialize_on_archive_row(engine: AsyncEngine) -> None:
    import asyncio

    session_id = uuid4()
    left, right = Store(engine), Store(engine)
    await opened(left, session_id)
    assert await asyncio.gather(
        left.append(session_id, [entry(1), entry(2)]),
        right.append(session_id, [entry(1), entry(2)]),
    ) == [2, 2]
    assert await right.read(session_id) == (2, [entry(1), entry(2)])
