"""Consumer-side session contracts; no transport-specific evidence or command queue."""

from typing import Protocol

from agentplane.protocol import command_pb2, event_log_pb2
from agentplane.runner import protocol_pb2

# gazelle:include_dep @pypi//protobuf


class SessionAttachment(Protocol):
    @property
    def attached(self) -> protocol_pb2.Attached: ...
    async def next_entry(self) -> event_log_pb2.EventEntry: ...
    def cancel(self) -> None: ...


class Sessions(Protocol):
    async def list_sessions(self) -> list[protocol_pb2.SessionSummary]: ...
    async def attach(self, session_id: str, *, after_cursor: int = 0) -> SessionAttachment: ...
    async def open(
        self, session_id: str, spec: dict[str, object], setup_script: str | None = None
    ) -> protocol_pb2.Attached: ...
    async def resume(self, session_id: str) -> protocol_pb2.Attached: ...
    async def command(
        self, session_id: str, command: command_pb2.Command, *, after_cursor: int
    ) -> event_log_pb2.EventEntry: ...
