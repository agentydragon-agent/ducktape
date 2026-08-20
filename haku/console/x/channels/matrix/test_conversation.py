"""What `conversation.py` does with a room: bind its conversation, keep a session running under
it, and take what is said in it into a turn.

Ingress is here rather than beside the turn loop it feeds: `MatrixTurns.offer` takes homeserver
events and hands them to `enqueue_prompt`, so a test of it is a test of the crossing. The turn loop's own admission rules are <../../test_session_runtime.py>, where no channel appears
at all. The conversation-history tests remain here beside the replacement-session setup that creates
their cross-session threads; the reader itself is channel-neutral.
"""

from __future__ import annotations

import datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import pytest_bazel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from haku.console.chat_models import (
    SPA_ORIGIN,
    ConversationEventKind,
    ItemType,
    MatrixOrigin,
    PromptRejection,
    RuntimeKind,
    SessionStatus,
    TurnOutcome,
)
from haku.console.database_schema import ChatAttachment, Conversation, ConversationEvent, ConversationItem, Session
from haku.console.x import session_events
from haku.console.x.channels.matrix.client import InboundMessage, UnmappableEvent
from haku.console.x.channels.matrix.conftest import MATRIX_CONFIG, MATRIX_OPERATOR, MATRIX_ROOM
from haku.console.x.channels.matrix.conversation import (
    ConversationFacts,
    MatrixConversationStore,
    MatrixSessionSupervisor,
    MatrixTurns,
    PromptAccepted,
    PromptRejected,
)
from haku.console.x.channels.matrix.ingress_ledger import IngressLedger
from haku.console.x.conftest import make_idle
from haku.console.x.conversation_events import (
    ConversationEvent as FoldedEvent,
    FrameRange,
    ItemSegment,
    MessageCompleted,
    MessageStarted,
    OpenRef,
)
from haku.console.x.conversation_history import ConversationHistory
from haku.console.x.session_events import PromptStartedBody
from haku.console.x.session_notifications import SessionNotifications
from haku.console.x.session_runtime import SessionService
from haku.console.x.session_store import ADOPTION_GRACE, BridgeAuthentication, SessionStore


async def session_behind_the_room(conversations: MatrixConversationStore) -> UUID | None:
    return await conversations.session_serving()


@pytest.fixture
def announced() -> list[str]:
    """What the supervisor said into the room."""
    return []


@pytest.fixture
def supervisor(
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    chat_service: SessionService,
    notifications: SessionNotifications,
    migrated_identity_store,
    announced: list[str],
) -> MatrixSessionSupervisor:
    """The supervisor over real stores, with only Kubernetes and the announce sink stood in."""

    async def _announce(body: str) -> None:
        announced.append(body)

    return MatrixSessionSupervisor(
        MATRIX_CONFIG,
        conversations,
        chat_service,
        chat_store,
        notifications,
        migrated_identity_store,
        _announce,
        engine=cast(Any, None),  # only `run()` takes the advisory lock; these drive `supervise_once`
    )


async def test_does_nothing_before_a_room_is_bound(supervisor, recording_claims, announced) -> None:
    """Nothing to serve, and nowhere to say so — provisioning here would be a sandbox nobody can reach."""

    await supervisor.supervise_once()

    assert (recording_claims.created, announced) == ([], [])


async def test_provisions_a_session_for_a_freshly_bound_room(
    supervisor, conversations, operator_id, chat_store, recording_claims, announced
) -> None:
    await conversations.bind_room(MATRIX_ROOM, operator_id)

    await supervisor.supervise_once()

    [session_id] = recording_claims.created
    assert await session_behind_the_room(conversations) == session_id
    assert await chat_store.status(session_id) == SessionStatus.PROVISIONING
    assert "provisioning a sandbox" in announced[0]


async def test_leaves_a_live_session_alone(supervisor, conversations, operator_id, recording_claims) -> None:
    await conversations.bind_room(MATRIX_ROOM, operator_id)
    await supervisor.supervise_once()
    [live] = recording_claims.created

    await supervisor.supervise_once()

    assert recording_claims.created == [live], "a live session was replaced"


async def test_an_idle_session_allocates_only_after_matrix_accepts_a_prompt(
    supervisor, conversations, turns, operator_id, chat_store, recording_claims, migrated_sessions
) -> None:
    binding = await conversations.bind_room(MATRIX_ROOM, operator_id)
    session, _ = await chat_store.create(operator_id, conversation_id=binding.conversation_id)
    await make_idle(migrated_sessions, session.session_id)

    await supervisor.supervise_once()
    assert recording_claims.created == [], "an empty room owns no sandbox"

    admitted = await turns.offer([operator_message("wake up", event_id="$wake", at=1)])
    assert isinstance(admitted, PromptAccepted)
    await supervisor.supervise_once()

    assert recording_claims.created == [session.session_id]
    assert await chat_store.status(session.session_id) == SessionStatus.PROVISIONING


async def test_replaces_a_failed_session(
    supervisor, conversations, operator_id, chat_store, recording_claims, announced
) -> None:
    """A dead session over Matrix is invisible — the room would just stop answering."""
    await conversations.bind_room(MATRIX_ROOM, operator_id)
    await supervisor.supervise_once()
    [dead] = recording_claims.created
    await chat_store.fail(dead, "the sandbox went away")

    await supervisor.supervise_once()

    assert len(recording_claims.created) == 2
    assert await session_behind_the_room(conversations) not in (None, dead)
    assert dead in recording_claims.deleted, "the dead session's claim must be swept before a new one is made"
    assert any("ended" in line for line in announced)
    # The status alone says a session died; only the reason says which failure it was, and the
    # room is the one place an operator is looking.
    assert any("the sandbox went away" in line for line in announced)


async def test_which_session_serves_the_room_is_read_off_the_thread(
    supervisor, conversations, operator_id, chat_store, recording_claims
) -> None:
    """Nothing points the room at a session: the answer is the newest session of the conversation
    the room's attachment names, which is what makes replacement invisible to the channel."""
    await conversations.bind_room(MATRIX_ROOM, operator_id)
    await supervisor.supervise_once()
    [first] = recording_claims.created
    await chat_store.fail(first, "the sandbox went away")

    await supervisor.supervise_once()

    [_, second] = recording_claims.created
    assert await session_behind_the_room(conversations) == second


async def test_a_replacement_session_joins_the_room_s_conversation_and_the_attachment_stays_put(
    supervisor, conversations, operator_id, chat_store, recording_claims, migrated_sessions
) -> None:
    """Session replacement is the supervisor's normal job, and the room's attachment is not touched
    by it: the successor joins the thread the attachment names."""
    await conversations.bind_room(MATRIX_ROOM, operator_id)
    await supervisor.supervise_once()
    [first] = recording_claims.created
    await chat_store.fail(first, "the sandbox went away")

    await supervisor.supervise_once()

    async with migrated_sessions() as db:
        threads = {row.session_id: row.conversation_id for row in await db.scalars(select(Session))}
        attachments = (
            await db.execute(select(ChatAttachment.conversation_id, ChatAttachment.address, ChatAttachment.detached_at))
        ).all()
    assert len(threads) == 2, "the failed session was replaced"
    assert len(set(threads.values())) == 1, "both sessions run one conversation"
    assert attachments == [(threads[first], MATRIX_ROOM, None)], "one live attachment, never re-pointed"


async def test_replaces_a_session_whose_replica_stopped_renewing_its_lease(
    supervisor, conversations, operator_id, chat_store, recording_claims, migrated_sessions, announced
) -> None:
    """A replica that went away without recording anything leaves a live status nothing is working
    on, and supervision has to reclaim it rather than believe it — but only once the lease has been
    adoptable for a whole `ADOPTION_GRACE` and no runner took it, which is what makes a console
    roll survivable rather than fatal.
    """
    await conversations.bind_room(MATRIX_ROOM, operator_id)
    await supervisor.supervise_once()
    [orphan] = recording_claims.created
    async with migrated_sessions.begin() as db:
        chat = await db.get(Session, orphan)
        assert chat is not None
        chat.lease_expires_at = datetime.datetime.now(datetime.UTC) - ADOPTION_GRACE - datetime.timedelta(seconds=1)

    await supervisor.supervise_once()

    assert len(recording_claims.created) == 2, "the orphaned session was believed rather than replaced"
    assert await session_behind_the_room(conversations) not in (None, orphan)
    assert any("ended" in line for line in announced)


async def test_replaces_a_session_whose_row_is_gone(
    supervisor, conversations, operator_id, recording_claims, migrated_sessions
) -> None:
    """A deleted session leaves the room's thread unserved, and the next pass re-provisions.

    What the schema allows is the session row being deleted underneath the conversation, which
    leaves it with no session rather than a dangling reference.
    """
    await conversations.bind_room(MATRIX_ROOM, operator_id)
    await supervisor.supervise_once()
    [vanished] = recording_claims.created

    async with migrated_sessions.begin() as db:
        await db.execute(delete(Session).where(Session.session_id == vanished))
    assert await session_behind_the_room(conversations) is None, "the thread should be left with no session"

    await supervisor.supervise_once()

    assert len(recording_claims.created) == 2
    assert await session_behind_the_room(conversations) not in (None, vanished)


async def test_does_not_repeat_an_unchanged_status(
    supervisor, conversations, operator_id, chat_store, recording_claims, announced
) -> None:
    """Every transition is reported, but a poll that changes nothing must not spam the room."""
    await conversations.bind_room(MATRIX_ROOM, operator_id)
    await supervisor.supervise_once()
    [session_id] = recording_claims.created
    # Provisioning already announced itself; the runner connecting is the next transition.
    assert (
        await chat_store.authenticate_bridge(session_id, recording_claims.tokens[session_id])
        == BridgeAuthentication.ACCEPTED
    )
    announced.clear()

    await supervisor.supervise_once()
    await supervisor.supervise_once()

    assert announced == [f"session {session_id} is ready"]


@pytest.fixture
def transcript(migrated_sessions) -> ConversationHistory:
    return ConversationHistory(migrated_sessions)


@pytest.fixture
async def thread(conversations: MatrixConversationStore, operator_id: UUID) -> UUID:
    """The conversation the room holds a copy of, opened the way an invite opens it."""
    return (await conversations.bind_room(MATRIX_ROOM, operator_id)).conversation_id


async def another_thread(sessions: async_sessionmaker[AsyncSession], operator_id: UUID) -> UUID:
    """A second conversation, inserted directly rather than bound.

    `bind_room` refuses a second room by design, so a test about two threads cannot ask for one
    through it — which is the point being made below.
    """
    conversation_id = uuid4()
    async with sessions.begin() as db:
        db.add(
            Conversation(
                conversation_id=conversation_id,
                operator_id=operator_id,
                runtime_kind=RuntimeKind.CLAUDE_CODE,
                created_at=datetime.datetime.now(datetime.UTC),
            )
        )
    return conversation_id


async def serving_session(chat_store: SessionStore, operator_id: UUID, conversation_id: UUID) -> UUID:
    """A Matrix session ready to take prompts, made the way the supervisor and a runner make one."""
    view, token = await chat_store.create(operator_id, conversation_id=conversation_id)
    assert await chat_store.authenticate_bridge(view.session_id, token) == BridgeAuthentication.ACCEPTED
    return view.session_id


async def exchange(chat_store: SessionStore, operator_id: UUID, session_id: UUID, asked: str, answered: str) -> None:
    """One question and its answer, written by the paths that write them in production.

    Not hand-inserted rows: this read depends on what the real writers leave behind — a prompt item
    the store opens and closes at admission, and a message item whose text is the segments the fold
    appended to it.
    """
    await chat_store.enqueue_prompt(operator_id, session_id, asked, SPA_ORIGIN)
    start = await chat_store.next_prompt(session_id)
    assert start is not None
    await say(chat_store, session_id, start.turn_id, answered)
    # Ended, because admission asks about the turn: a session left mid-turn refuses the next
    # prompt, and these tests are conversations rather than one exchange each.
    await chat_store.end_turn(start.turn_id, TurnOutcome.ANSWERED)


async def say(
    chat_store: SessionStore, session_id: UUID, turn_id: UUID, answered: str, *, complete: bool = True
) -> None:
    """One agent message, through the fold's own vocabulary."""
    where = FrameRange(1, 1)
    events: list[FoldedEvent] = [MessageStarted(provenance=where)]
    if answered:
        events.append(ItemSegment(item=OpenRef(item_type=ItemType.MESSAGE), text=answered, provenance=where))
    if complete:
        events.append(MessageCompleted(backend_item_id=None, provenance=where))
    await chat_store.apply_frame(session_id, turn_id, 1, events)


async def read(transcript: ConversationHistory, conversation_id: UUID) -> list[tuple[ItemType, str]]:
    """A thread's recent conversation as a replacement session that owns none of it would read it."""
    return [
        (message.item_type, message.body)
        for message in await transcript.recent(conversation_id, before_session=uuid4(), limit=20)
    ]


async def test_the_transcript_is_both_sides_of_the_conversation_in_order(
    transcript: ConversationHistory, chat_store: SessionStore, operator_id: UUID, thread: UUID
) -> None:
    session_id = await serving_session(chat_store, operator_id, thread)

    await exchange(chat_store, operator_id, session_id, "hi", "hello")
    await exchange(chat_store, operator_id, session_id, "still there?", "yes")

    assert await read(transcript, thread) == [
        (ItemType.PROMPT, "hi"),
        (ItemType.MESSAGE, "hello"),
        (ItemType.PROMPT, "still there?"),
        (ItemType.MESSAGE, "yes"),
    ]


async def test_the_transcript_spans_every_session_of_the_thread(
    transcript: ConversationHistory, chat_store: SessionStore, operator_id: UUID, thread: UUID
) -> None:
    """The point of reading by conversation: the session that holds the context is the one gone.

    Sessions of one thread share `conversation_id`, so a replacement reads what its predecessor
    said without either of them being named.
    """
    first = await serving_session(chat_store, operator_id, thread)
    await exchange(chat_store, operator_id, first, "hi", "hello")
    await chat_store.fail(first, "the sandbox went away")
    second = await serving_session(chat_store, operator_id, thread)
    await exchange(chat_store, operator_id, second, "again", "still here")

    assert await read(transcript, thread) == [
        (ItemType.PROMPT, "hi"),
        (ItemType.MESSAGE, "hello"),
        (ItemType.PROMPT, "again"),
        (ItemType.MESSAGE, "still here"),
    ]


async def test_a_batch_the_dying_session_never_answered_is_still_the_history(
    transcript: ConversationHistory, chat_store: SessionStore, operator_id: UUID, thread: UUID
) -> None:
    """What answers a message its session never got to: the replacement is handed it as context.

    The batch is acknowledged the moment it is accepted, so nothing offers it again — the prompt
    row ingress wrote is the whole of what survives, and this is the read that finds it.
    """
    doomed = await serving_session(chat_store, operator_id, thread)
    await exchange(chat_store, operator_id, doomed, "hi", "hello")
    # Accepted, and then nothing: no turn ever claimed it, which is what leaves it `pending`.
    await chat_store.enqueue_prompt(operator_id, doomed, "the one that killed it", SPA_ORIGIN)
    await chat_store.fail(doomed, "the sandbox went away")

    assert (ItemType.PROMPT, "the one that killed it") in await read(transcript, thread)


async def test_a_session_s_own_rows_are_not_its_history(
    transcript: ConversationHistory, chat_store: SessionStore, operator_id: UUID, thread: UUID
) -> None:
    """A prompt this session has already been handed is not also its history; twice is not context.

    The window is real: a session goes `ready` when its runner authenticates, and its system
    prompt is rendered a few statements later — so a batch can be accepted in between.
    """
    doomed = await serving_session(chat_store, operator_id, thread)
    await exchange(chat_store, operator_id, doomed, "hi", "hello")
    replacement = await serving_session(chat_store, operator_id, thread)
    await chat_store.enqueue_prompt(operator_id, replacement, "re-offered", SPA_ORIGIN)

    said = await transcript.recent(thread, before_session=replacement, limit=20)

    assert [(message.item_type, message.body) for message in said] == [
        (ItemType.PROMPT, "hi"),
        (ItemType.MESSAGE, "hello"),
    ]


async def test_what_the_room_was_never_told_is_not_in_the_history(
    transcript: ConversationHistory, chat_store: SessionStore, operator_id: UUID, thread: UUID
) -> None:
    """Haku's side is here on exactly the condition the room heard it on.

    Two items exist that were never an answer, and neither is context: one still being written into
    when its session died, and the empty one a turn that only ran tools leaves behind.
    """
    session_id = await serving_session(chat_store, operator_id, thread)
    await chat_store.enqueue_prompt(operator_id, session_id, "do something", SPA_ORIGIN)
    start = await chat_store.next_prompt(session_id)
    assert start is not None
    await say(chat_store, session_id, start.turn_id, "")
    await say(chat_store, session_id, start.turn_id, "half an ans", complete=False)

    assert await read(transcript, thread) == [(ItemType.PROMPT, "do something")]


async def test_another_thread_is_not_this_thread(
    transcript: ConversationHistory,
    migrated_sessions: async_sessionmaker[AsyncSession],
    chat_store: SessionStore,
    operator_id: UUID,
    thread: UUID,
) -> None:
    """Threads are read apart even though the console services one room at a time, which is what a
    second attached room will need on the day one bot holds several."""
    elsewhere = await serving_session(chat_store, operator_id, await another_thread(migrated_sessions, operator_id))

    await exchange(chat_store, operator_id, elsewhere, "hi", "hello")

    assert await read(transcript, thread) == []


async def test_the_limit_takes_the_tail(
    transcript: ConversationHistory, chat_store: SessionStore, operator_id: UUID, thread: UUID
) -> None:
    session_id = await serving_session(chat_store, operator_id, thread)
    await exchange(chat_store, operator_id, session_id, "one", "re: one")
    await exchange(chat_store, operator_id, session_id, "two", "re: two")

    said = await transcript.recent(thread, before_session=uuid4(), limit=2)

    assert [message.body for message in said] == ["two", "re: two"], "the newest, still oldest first"


@pytest.fixture
def turns(
    conversations: MatrixConversationStore, chat_store: SessionStore, migrated_identity_store, ledger: IngressLedger
) -> MatrixTurns:
    """Ingress over the real stores — only the homeserver's events are handed in by the test."""
    return MatrixTurns(MATRIX_CONFIG, conversations, chat_store, migrated_identity_store, ledger)


async def serving_room(conversations: MatrixConversationStore, operator_id: UUID) -> None:
    """Bind the room, the way an invite does before the supervisor provisions anything.

    Which session then serves it is read off the thread, so binding is all there is to arrange.
    """
    assert (await conversations.bind_room(MATRIX_ROOM, operator_id)).room_id == MATRIX_ROOM


def operator_message(body: str, *, event_id: str, at: int) -> InboundMessage:
    """The operator saying *body* in the room, as `/sync` hands it over."""
    return InboundMessage(
        room_id=MATRIX_ROOM, event_id=event_id, sender=MATRIX_OPERATOR, body=body, origin_server_ts=at
    )


def _unmappable(msgtype: str) -> UnmappableEvent:
    return UnmappableEvent(room_id=MATRIX_ROOM, event_id=f"${msgtype}", sender=MATRIX_OPERATOR, msgtype=msgtype)


async def test_a_batch_a_ready_session_takes_becomes_its_prompt(
    turns: MatrixTurns,
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    operator_id: UUID,
    thread: UUID,
) -> None:
    """The accepted case, and what "one batch, one prompt" means: two events, one transcript row."""
    session_id = await serving_session(chat_store, operator_id, thread)
    await serving_room(conversations, operator_id)

    admitted = await turns.offer(
        [operator_message("hi", event_id="$1", at=1), operator_message("and this", event_id="$2", at=2)]
    )

    assert isinstance(admitted, PromptAccepted)
    start = await chat_store.next_prompt(session_id)
    assert start is not None
    assert start.prompt == "hi\nand this", "the ids ride on the prompt's own event now, not in its prose"


async def test_a_batch_offered_mid_turn_is_rejected_with_the_reason_and_the_text(
    turns: MatrixTurns,
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    operator_id: UUID,
    thread: UUID,
) -> None:
    """A message sent while Haku is working is answered rather than queued behind the turn, and the
    row it hands back is the only copy of what was said — the homeserver will not offer it again
    once the caller acknowledges the batch."""
    session_id = await serving_session(chat_store, operator_id, thread)
    await serving_room(conversations, operator_id)
    await chat_store.enqueue_prompt(operator_id, session_id, "first", SPA_ORIGIN)
    assert await chat_store.next_prompt(session_id) is not None

    admitted = await turns.offer([operator_message("and another thing", event_id="$2", at=2)])

    assert isinstance(admitted, PromptRejected)
    assert admitted.reason is PromptRejection.TURN_IN_FLIGHT
    assert admitted.facts is not None
    assert (admitted.facts.conversation_id, admitted.facts.session_id) == (thread, session_id)
    assert admitted.facts.bodies == (
        session_events.PromptRejectedBody(reason=PromptRejection.TURN_IN_FLIGHT, text="and another thing"),
    )


async def test_a_batch_offered_before_a_session_exists_is_still_recorded(
    turns: MatrixTurns, conversations: MatrixConversationStore, chat_store: SessionStore, operator_id: UUID
) -> None:
    """A room bound before the supervisor has provisioned anything.

    What a refusal is about is the conversation, which exists as soon as the room is bound — so this
    is a row like any other refusal's, with no session named because there was none. What it used to
    be was the one case the record could not carry, said into the room by ingress and nowhere else.
    """
    bound = await conversations.bind_room(MATRIX_ROOM, operator_id)

    admitted = await turns.offer([operator_message("hi", event_id="$1", at=1)])

    assert admitted == PromptRejected(
        reason=PromptRejection.NO_SESSION,
        facts=ConversationFacts(
            conversation_id=bound.conversation_id,
            session_id=None,
            bodies=(session_events.PromptRejectedBody(reason=PromptRejection.NO_SESSION, text="hi"),),
        ),
    )


async def test_a_batch_offered_to_a_session_that_is_gone_is_rejected_rather_than_raised(
    turns: MatrixTurns,
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    migrated_sessions,
    operator_id: UUID,
    thread: UUID,
) -> None:
    """The supervisor is between sessions, which the room must survive.

    `enqueue_prompt` answers a vanished session with `KeyError`; raising that into the sync loop
    would cost the operator an answer. It reads as the case above — recorded against the
    conversation with no session named, because there is none.
    """
    session_id = await serving_session(chat_store, operator_id, thread)
    await serving_room(conversations, operator_id)
    async with migrated_sessions.begin() as db:
        await db.execute(delete(Session).where(Session.session_id == session_id))

    admitted = await turns.offer([operator_message("hi", event_id="$1", at=1)])

    assert isinstance(admitted, PromptRejected)
    assert admitted.reason is PromptRejection.NO_SESSION
    assert admitted.facts is not None
    assert (admitted.facts.conversation_id, admitted.facts.session_id) == (thread, None)


async def test_an_accepted_batch_records_its_events_against_the_prompt_it_became(
    turns: MatrixTurns,
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    ledger: IngressLedger,
    operator_id: UUID,
    thread: UUID,
) -> None:
    """The dedupe key, written where it cannot come apart from the prompt.

    A rejected batch records nothing, because there is no prompt for a row to name and the
    homeserver re-offering it is the outcome we want.
    """
    await serving_session(chat_store, operator_id, thread)
    await serving_room(conversations, operator_id)

    await turns.offer([operator_message("hi", event_id="$1", at=1), operator_message("more", event_id="$2", at=2)])

    assert await ledger.carried(["$1", "$2", "$3"]) == frozenset({"$1", "$2"})


async def test_a_rejected_batch_records_nothing_for_the_homeserver_to_be_deduped_against(
    turns: MatrixTurns,
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    ledger: IngressLedger,
    operator_id: UUID,
    thread: UUID,
) -> None:
    session_id = await serving_session(chat_store, operator_id, thread)
    await serving_room(conversations, operator_id)
    await chat_store.enqueue_prompt(operator_id, session_id, "first", SPA_ORIGIN)
    assert await chat_store.next_prompt(session_id) is not None

    assert isinstance(await turns.offer([operator_message("hi", event_id="$1", at=1)]), PromptRejected)

    assert await ledger.carried(["$1"]) == frozenset()


async def test_a_prompt_its_session_never_answered_is_taken_by_the_replacement(
    turns: MatrixTurns,
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    ledger: IngressLedger,
    operator_id: UUID,
    thread: UUID,
) -> None:
    """Suppression is not acknowledgement: the batch was acknowledged to the homeserver, so this
    prompt is the only copy left of what the operator asked, and the session holding it died.

    Nothing re-offers it. The queue belongs to the conversation, so the replacement's own
    `next_prompt` finds the same row — what this replaces was a ledger query for stranded prompts
    and a channel that asked the live session the dead one's question.
    """
    doomed = await serving_session(chat_store, operator_id, thread)
    await serving_room(conversations, operator_id)
    await turns.offer([operator_message("did you see this", event_id="$1", at=1)])
    await chat_store.closed(doomed)
    replacement = await serving_session(chat_store, operator_id, thread)

    start = await chat_store.next_prompt(replacement)

    assert start is not None
    assert start.prompt == "did you see this"
    assert await ledger.carried(["$1"]) == frozenset({"$1"}), "and the homeserver's re-delivery is still dropped"


async def test_an_unreadable_event_is_a_fact_per_event_on_the_live_conversation(
    turns: MatrixTurns,
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    operator_id: UUID,
    thread: UUID,
) -> None:
    """One fact per event, for the caller to append in the transaction that acknowledges the batch
    (<../../../debug/channel_write_audit.md> row 12)."""
    session_id = await serving_session(chat_store, operator_id, thread)
    await serving_room(conversations, operator_id)

    facts = await turns.unreadable([_unmappable("m.image"), _unmappable("m.audio")])

    assert facts == ConversationFacts(
        conversation_id=thread,
        session_id=session_id,
        bodies=(
            session_events.UnreadableInputBody(media_type="m.image"),
            session_events.UnreadableInputBody(media_type="m.audio"),
        ),
    )


async def test_an_unreadable_event_with_no_session_behind_the_room_is_still_recorded(
    turns: MatrixTurns, conversations: MatrixConversationStore, operator_id: UUID
) -> None:
    """Same terms as a refusal: the conversation is what it is about, and it exists from the moment
    the room is bound. Only a room bound to nothing has nowhere to record it — and nowhere to say
    it either, which makes the two absences the same one."""
    bound = await conversations.bind_room(MATRIX_ROOM, operator_id)

    facts = await turns.unreadable([_unmappable("m.image")])

    assert facts == ConversationFacts(
        conversation_id=bound.conversation_id,
        session_id=None,
        bodies=(session_events.UnreadableInputBody(media_type="m.image"),),
    )


async def test_a_batch_records_the_room_events_it_was_folded_from(
    turns: MatrixTurns,
    conversations: MatrixConversationStore,
    chat_store: SessionStore,
    migrated_sessions,
    operator_id: UUID,
    thread: UUID,
) -> None:
    """The prompt is what was said; which events said it rides on the prompt's own event, in the
    order they were folded. Nothing puts an event id in the text any more, so this is the
    only copy — and it names the room as well as the event, which is what a reader comparing
    origins needs once one bot serves more than one.
    """
    await serving_session(chat_store, operator_id, thread)
    await serving_room(conversations, operator_id)

    offered = await turns.offer(
        [operator_message("first", event_id="$a", at=1), operator_message("second", event_id="$b", at=2)]
    )

    assert isinstance(offered, PromptAccepted)
    async with migrated_sessions() as db:
        prompt = await db.get(ConversationItem, offered.item_id)
        assert prompt is not None
        assert (prompt.item_type, prompt.item_text) == (ItemType.PROMPT, "first\nsecond")
        asked = await db.scalar(
            select(ConversationEvent).where(
                ConversationEvent.item_id == offered.item_id,
                ConversationEvent.kind == ConversationEventKind.ITEM_STARTED,
            )
        )
    assert asked is not None
    assert PromptStartedBody.model_validate(asked.body).origin == MatrixOrigin(address=MATRIX_ROOM, refs=("$a", "$b"))


if __name__ == "__main__":
    pytest_bazel.main()
