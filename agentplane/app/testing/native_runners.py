"""Native transport doubles for app archive tests; production always uses Sandbox Service gRPC."""

from __future__ import annotations


import asyncio

from google.protobuf.json_format import ParseDict
from agentplane.protocol import command_pb2, event_log_pb2
from agentplane.runner import protocol_pb2
from agentplane.sandbox_service.command_relay import admit_running_command
from agentplane.sandbox_service.session_lifecycle import resume_session
from agentplane.app.agent_runtime.runner.runners import SandboxNotReachableError
from agentplane.app.changes import Changes
from agentplane.app.live import LiveIndex
from agentplane.runner.client import RunnerClient
from agentplane.sandbox_service.inventory import ProvisioningState, SandboxNotFoundError


# gazelle:include_dep @pypi//protobuf


class Runners:
    def __init__(self, index: LiveIndex, port: int) -> None:
        self._index = index
        self._port = port
        self._clients: dict[str, NativeSessions] = {}

    @property
    def changes(self) -> Changes:
        """Wakes when the running set may have changed; it is the index's own signal."""
        return self._index.changes

    def running(self) -> set[str]:
        return {view.name for view in self._index.sandbox_views() if view.state is ProvisioningState.RUNNING}

    def client(self, sandbox: str) -> NativeSessions:
        view = self._index.sandbox_view(sandbox)
        if view is None:
            raise SandboxNotFoundError(sandbox)
        if view.state is not ProvisioningState.RUNNING or view.pod is None or view.pod.ip is None:
            raise SandboxNotReachableError(sandbox, view.state)
        address = f"{view.pod.ip}:{self._port}"
        if address not in self._clients:
            self._clients[address] = NativeSessions(address)
        return self._clients[address]

    async def close(self) -> None:
        await asyncio.gather(*(client.close() for client in self._clients.values()))


class NativeSessions(RunnerClient):
    """Transport double for app archive/replication tests, not a production access path."""

    async def open(self, session_id: str, spec: dict[str, object], setup_script: str | None = None) -> protocol_pb2.Attached:
        attachment = await self.attach(session_id, spec=ParseDict(spec, protocol_pb2.SessionSpec()), setup_script=setup_script)
        try:
            return attachment.attached
        finally:
            attachment.cancel()

    async def resume(self, session_id: str) -> protocol_pb2.Attached:
        return await resume_session(self, session_id)

    async def command(self, session_id: str, command: command_pb2.Command, *, after_cursor: int) -> event_log_pb2.EventEntry:
        return await admit_running_command(self, session_id, command, after_cursor=after_cursor, timeout_s=15)
