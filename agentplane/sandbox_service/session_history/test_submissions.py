"""Draft acceptance/reconciliation contract against migrated PostgreSQL, not a live service."""

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_bazel
from sqlalchemy.ext.asyncio import AsyncEngine

from agentplane.protocol import command_pb2, event_log_pb2
from agentplane.sandbox_service.session_history.store import HistoryConflictError, Store
from agentplane.sandbox_service.session_history.submissions import (
    InputMetadata,
    NotificationNotice,
    SubmissionConflictError,
    SubmissionNotFoundError,
    SubmissionRefusedError,
    SubmissionState,
    SubmissionStore,
    SubmitInput,
    submit_input,
)
from agentplane.subjects import ServiceAccountRef

# gazelle:include_dep @pypi//protobuf

pytestmark = pytest.mark.asyncio
CALLER = ServiceAccountRef(namespace="testing", name="notifications")
PRODUCERS = frozenset({CALLER})


def admission(command: command_pb2.Command, cursor: int = 1) -> event_log_pb2.EventEntry:
    result = event_log_pb2.EventEntry(cursor=cursor)
    result.origin.source_id = "runner-source"
    result.origin.sequence = cursor
    result.event.command_admitted.command.CopyFrom(command)
    return result


@pytest.fixture
async def history(engine: AsyncEngine) -> tuple[Store, SubmissionStore, UUID]:
    session_id = uuid4()
    archive = Store(engine)
    await archive.open(
        session_id,
        sandbox_namespace="testing",
        sandbox_name="sandbox",
        sandbox_uid=uuid4(),
        runner_session_id="runner-session",
    )
    return archive, SubmissionStore(engine), session_id


async def test_persist_before_dispatch_and_keep_metadata_out_of_runner(
    history: tuple[Store, SubmissionStore, UUID],
) -> None:
    archive, store, session_id = history
    request = SubmitInput(
        command_id="notice",
        text="notice text",
        metadata=InputMetadata(notification_notice=NotificationNotice(inbox_id=uuid4(), through_cursor=12)),
    )

    async def dispatch(command: command_pb2.Command) -> event_log_pb2.EventEntry:
        assert (await store.read(session_id, "notice")).state == SubmissionState.PENDING_ADMISSION
        assert command == command_pb2.Command(
            command_id="notice", submit_input=command_pb2.SubmitInput(text="notice text")
        )
        return admission(command)

    receipt = await submit_input(
        store, session_id, request, caller=CALLER, notification_producers=PRODUCERS, dispatch=dispatch
    )
    assert receipt == admission(request.runner_command())
    assert (await store.read(session_id, "notice")).state == SubmissionState.ADMITTED
    # A direct receipt is not permission to skip the archive prefix.
    assert await archive.read(session_id) == (0, [])
    await archive.append(session_id, [receipt])
    await archive.append(session_id, [receipt])
    assert (await store.read(session_id, "notice")).receipt() == receipt


async def test_lost_reply_recovers_via_spool_and_new_store(
    history: tuple[Store, SubmissionStore, UUID], engine: AsyncEngine
) -> None:
    archive, store, session_id = history
    request = SubmitInput(command_id="lost", text="hello")
    receipt = admission(request.runner_command())

    async def lost_reply(command: command_pb2.Command) -> event_log_pb2.EventEntry:
        raise TimeoutError("runner may have committed")

    with pytest.raises(TimeoutError):
        await submit_input(
            store, session_id, request, caller=CALLER, notification_producers=PRODUCERS, dispatch=lost_reply
        )
    assert (await store.read(session_id, "lost")).state == SubmissionState.PENDING_ADMISSION
    await archive.append(session_id, [receipt])

    async def must_not_dispatch(command: command_pb2.Command) -> event_log_pb2.EventEntry:
        raise AssertionError("an admitted retry must not dispatch")

    assert (
        await submit_input(
            SubmissionStore(engine),
            session_id,
            request,
            caller=CALLER,
            notification_producers=PRODUCERS,
            dispatch=must_not_dispatch,
        )
        == receipt
    )


async def test_ingestion_and_direct_receipt_race(history: tuple[Store, SubmissionStore, UUID]) -> None:
    archive, store, session_id = history
    request = SubmitInput(command_id="race", text="hello")
    await store.accept(session_id, request, caller=CALLER, notification_producers=PRODUCERS)
    receipt = admission(request.runner_command())
    await asyncio.gather(archive.append(session_id, [receipt]), store.admitted(session_id, receipt))
    assert (await store.read(session_id, "race")).receipt() == receipt
    assert (await store.rejected(session_id, "race", "late refusal")).state == SubmissionState.ADMITTED


async def test_reconciliation_and_checkpoint_roll_back_together(history: tuple[Store, SubmissionStore, UUID]) -> None:
    archive, store, session_id = history
    request = SubmitInput(command_id="atomic", text="hello")
    await store.accept(session_id, request, caller=CALLER, notification_producers=PRODUCERS)
    receipt = admission(request.runner_command())
    with pytest.raises(HistoryConflictError, match="expected 2"):
        await archive.append(session_id, [receipt, admission(request.runner_command(), 3)])
    assert await archive.read(session_id) == (0, [])
    assert (await store.read(session_id, "atomic")).state == SubmissionState.PENDING_ADMISSION
    await archive.append(session_id, [receipt])
    assert (await store.read(session_id, "atomic")).state == SubmissionState.ADMITTED


async def test_concurrent_identical_and_conflicting_acceptance(
    history: tuple[Store, SubmissionStore, UUID], engine: AsyncEngine
) -> None:
    _, store, session_id = history
    request = SubmitInput(command_id="same", text="original")
    results = await asyncio.gather(
        *[
            SubmissionStore(engine).accept(session_id, request, caller=CALLER, notification_producers=PRODUCERS)
            for _ in range(3)
        ]
    )
    assert all(result.state == SubmissionState.PENDING_ADMISSION for result in results)
    changed = [
        SubmitInput(command_id="same", text="different"),
        SubmitInput(
            command_id="same",
            text="original",
            metadata=InputMetadata(notification_notice=NotificationNotice(inbox_id=uuid4(), through_cursor=1)),
        ),
    ]
    for conflict in changed:
        with pytest.raises(SubmissionConflictError):
            await store.accept(session_id, conflict, caller=CALLER, notification_producers=PRODUCERS)
    with pytest.raises(SubmissionConflictError):
        await store.accept(
            session_id,
            request,
            caller=ServiceAccountRef(namespace="testing", name="other"),
            notification_producers=PRODUCERS,
        )


async def test_provenance_denied_before_persistence_and_on_retry(history: tuple[Store, SubmissionStore, UUID]) -> None:
    _, store, session_id = history
    request = SubmitInput(
        command_id="notice",
        text="notice",
        metadata=InputMetadata(notification_notice=NotificationNotice(inbox_id=uuid4(), through_cursor=1)),
    )
    with pytest.raises(PermissionError):
        await store.accept(session_id, request, caller=CALLER, notification_producers=frozenset())
    with pytest.raises(SubmissionNotFoundError):
        await store.read(session_id, "notice")
    await store.accept(session_id, request, caller=CALLER, notification_producers=PRODUCERS)
    with pytest.raises(PermissionError):
        await store.accept(session_id, request, caller=CALLER, notification_producers=frozenset())


async def test_definitive_refusal_is_retained(history: tuple[Store, SubmissionStore, UUID]) -> None:
    _, store, session_id = history
    request = SubmitInput(command_id="refused", text="hello")
    attempts = 0

    async def refuse(command: command_pb2.Command) -> event_log_pb2.EventEntry:
        nonlocal attempts
        attempts += 1
        raise SubmissionRefusedError("definitive refusal")

    for _ in range(2):
        with pytest.raises(SubmissionRefusedError, match="definitive refusal"):
            await submit_input(
                store, session_id, request, caller=CALLER, notification_producers=PRODUCERS, dispatch=refuse
            )
    assert attempts == 1
    assert (await store.read(session_id, "refused")).state == SubmissionState.REJECTED


async def test_bad_receipt_never_advances_submission(history: tuple[Store, SubmissionStore, UUID]) -> None:
    _, store, session_id = history
    request = SubmitInput(command_id="original", text="hello")
    await store.accept(session_id, request, caller=CALLER, notification_producers=PRODUCERS)
    with pytest.raises(SubmissionConflictError):
        await store.admitted(session_id, admission(SubmitInput(command_id="original", text="changed").runner_command()))
    assert (await store.read(session_id, "original")).state == SubmissionState.PENDING_ADMISSION


async def test_cancelled_dispatch_stays_pending(history: tuple[Store, SubmissionStore, UUID]) -> None:
    _, store, session_id = history
    request = SubmitInput(command_id="cancelled", text="hello")

    async def cancel(command: command_pb2.Command) -> event_log_pb2.EventEntry:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await submit_input(store, session_id, request, caller=CALLER, notification_producers=PRODUCERS, dispatch=cancel)
    assert (await store.read(session_id, "cancelled")).state == SubmissionState.PENDING_ADMISSION


if __name__ == "__main__":
    pytest_bazel.main()
