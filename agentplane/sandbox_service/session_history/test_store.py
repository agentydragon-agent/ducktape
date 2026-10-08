"""Real PostgreSQL exercises transactional history, including independent replay."""

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_bazel
from sqlalchemy.ext.asyncio import AsyncEngine

from agentplane.protocol import event_log_pb2
from agentplane.sandbox_service.session_history.store import HistoryConflictError, HistoryNotFoundError, Store

# gazelle:include_dep @pypi//protobuf


def entry(cursor: int, source: str = "source", *, resumed: bool = False) -> event_log_pb2.EventEntry:
    result = event_log_pb2.EventEntry(cursor=cursor)
    result.origin.source_id = source
    result.origin.sequence = cursor
    result.event.harness_started.resumed = resumed
    return result


async def opened(store: Store, session_id: UUID) -> None:
    await store.open(
        session_id,
        sandbox_namespace="testing",
        sandbox_name="gone",
        sandbox_uid=None,
        runner_session_id="original-native-path",
    )


@pytest.mark.asyncio
async def test_replay_survives_new_store_and_deleted_sandbox(engine: AsyncEngine) -> None:
    session_id = uuid4()
    store = Store(engine)
    await opened(store, session_id)
    await opened(store, session_id)
    native = entry(3)
    native.event.ClearField("harness_started")
    native.event.native.line = "frame with a NUL\x00 and provider bytes"
    assert await store.append(session_id, [entry(1), entry(2, resumed=True)]) == 2
    assert await Store(engine).append(session_id, [entry(1), entry(2, resumed=True), native]) == 3
    high_water, events = await Store(engine).read(session_id, after_cursor=1, limit=2)
    assert high_water == 3
    assert events == [entry(2, resumed=True), native]
    assert await Store(engine).read(session_id, after_cursor=3) == (3, [])
    with pytest.raises(ValueError, match="beyond"):
        await store.read(session_id, after_cursor=4)


@pytest.mark.asyncio
async def test_bad_batch_rolls_back_and_conflicting_duplicate_rejected(engine: AsyncEngine) -> None:
    store = Store(engine)
    session_id = uuid4()
    await opened(store, session_id)
    with pytest.raises(HistoryConflictError, match="expected 2"):
        await store.append(session_id, [entry(1), entry(3)])
    assert await store.read(session_id) == (0, [])
    assert await store.append(session_id, [entry(1), entry(2)]) == 2
    for bad in ([entry(2, resumed=True)], [entry(3, "other")], [entry(4)]):
        with pytest.raises(HistoryConflictError):
            await store.append(session_id, bad)
    assert await store.read(session_id) == (2, [entry(1), entry(2)])
    with pytest.raises(HistoryConflictError, match="locator"):
        await store.open(
            session_id,
            sandbox_namespace="testing",
            sandbox_name="new",
            sandbox_uid=None,
            runner_session_id="original-native-path",
        )
    with pytest.raises(HistoryNotFoundError):
        await store.append(uuid4(), [entry(1)])


@pytest.mark.asyncio
async def test_two_replica_writers_serialize_on_history_row(engine: AsyncEngine) -> None:
    session_id = uuid4()
    left, right = Store(engine), Store(engine)
    await opened(left, session_id)
    results = await asyncio.gather(
        left.append(session_id, [entry(1), entry(2)]), right.append(session_id, [entry(1), entry(2)])
    )
    assert list(results) == [2, 2]
    assert await right.read(session_id) == (2, [entry(1), entry(2)])


@pytest.mark.asyncio
async def test_registration_is_stable_across_retries_and_replicas(engine: AsyncEngine) -> None:
    left, right = Store(engine), Store(engine)
    uid = uuid4()
    locator = dict(sandbox_namespace="testing", sandbox_name="worker", sandbox_uid=uid, runner_session_id="s-1")
    first, second = await asyncio.gather(left.register(**locator), right.register(**locator))
    assert first == second
    assert await Store(engine).register(**locator) == first
    assert await left.read(first) == (0, [])
    assert await left.register(**(locator | {"sandbox_uid": uuid4()})) != first
    assert await left.register(**(locator | {"runner_session_id": "s-2"})) != first


@pytest.mark.asyncio
async def test_registration_reuses_imported_history_and_rejects_identity_collision(engine: AsyncEngine) -> None:
    store = Store(engine)
    session_id, uid = uuid4(), uuid4()
    await store.open(
        session_id,
        sandbox_namespace="testing",
        sandbox_name="worker",
        sandbox_uid=uid,
        runner_session_id="s-1",
    )
    assert await store.register(
        sandbox_namespace="testing", sandbox_name="worker", sandbox_uid=uid, runner_session_id="s-1"
    ) == session_id
    with pytest.raises(HistoryConflictError, match="belongs to another"):
        await store.open(
            uuid4(),
            sandbox_namespace="testing",
            sandbox_name="worker",
            sandbox_uid=uid,
            runner_session_id="s-1",
        )
    # A nullable legacy UID must not permit another ID for the same legacy locator.
    await opened(store, uuid4())
    with pytest.raises(HistoryConflictError, match="belongs to another"):
        await opened(store, uuid4())


if __name__ == "__main__":
    pytest_bazel.main()
