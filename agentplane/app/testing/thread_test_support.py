"""Shared thread/event values used by app and thread-store tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from google.protobuf.timestamp_pb2 import Timestamp

from agentplane.app.operator_sessions import OperatorSessionStore
from agentplane.app.threads.events.event_log import EventLogStore
from agentplane.app.threads.ingestion import Ingestion
from agentplane.app.threads.store import ThreadStore
from agentplane.protocol import event_log_pb2, event_pb2
from agentplane.runner import protocol_pb2


@dataclass(frozen=True)
class Replica:
    """Another app replica's stores, over its own connection pool on the same database."""

    store: ThreadStore
    event_logs: EventLogStore
    ingestion: Ingestion
    operator_sessions: OperatorSessionStore


SPEC = protocol_pb2.SessionSpec(
    harness=protocol_pb2.HARNESS_CLAUDE, cwd="/state/work", model="test-model", reasoning_effort="low"
)


# The three waits a `RunnerBridge` under test is built with. The bridge takes them from config and has
# no defaults of its own, so a test states what it runs with instead of inheriting a production number.
# These are the values the bridge ran under before the settings existed; nothing here waits on them, so
# their only job is to be generous enough that no test passes or fails because of them. A test that
# exercises a deadline names it explicitly instead of using this.
#
# A `TypedDict`, not a `dict[str, float]`, because callers pass it with `**`: the keys have to stay
# literal for a type checker to bind them to the bridge's parameters rather than any other keyword.
class BridgeWaitBudgets(TypedDict):
    command_admission_timeout_s: float
    session_archive_timeout_s: float
    admission_reread_s: float


BRIDGE_WAIT_BUDGETS: BridgeWaitBudgets = {
    "command_admission_timeout_s": 300.0,
    "session_archive_timeout_s": 60.0,
    "admission_reread_s": 2.0,
}


def event_entry(cursor: int, **observation: object) -> event_log_pb2.EventEntry:
    """One runner event at `cursor`, timestamped from it so a thread's order is its cursor order."""
    at = Timestamp()
    at.FromDatetime(datetime(2026, 9, 2, 12, 0, tzinfo=UTC) + timedelta(seconds=cursor))
    event = event_pb2.Event(at=at, **observation)  # type: ignore[arg-type]
    return event_log_pb2.EventEntry(
        cursor=cursor, origin=event_log_pb2.EventOrigin(source_id="test-runner", sequence=cursor), event=event
    )
