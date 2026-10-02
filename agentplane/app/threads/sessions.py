"""App-side session discovery; every runner operation goes through Sandbox Service."""

from agentplane.app.changes import Changes
from agentplane.app.live import LiveIndex
from agentplane.sandbox_service.client import Runner, SandboxServiceClient
from agentplane.sandbox_service.models import ProvisioningState, SandboxDestination, SandboxNotFoundError


class SandboxNotReachableError(Exception):
    def __init__(self, name: str, state: ProvisioningState) -> None:
        super().__init__(f"sandbox {name=} has no reachable runner: it is {state}")
        self.name = name


class SandboxSessions:
    def __init__(self, index: LiveIndex, service: SandboxServiceClient) -> None:
        self._index = index
        self._service = service
        self._clients: dict[SandboxDestination, Runner] = {}

    @property
    def changes(self) -> Changes:
        return self._index.changes

    def running(self) -> set[str]:
        return {view.name for view in self._index.sandbox_views() if view.state is ProvisioningState.RUNNING}

    def client(self, sandbox: str) -> Runner:
        view = self._index.sandbox_view(sandbox)
        if view is None:
            raise SandboxNotFoundError(sandbox)
        if view.state is not ProvisioningState.RUNNING:
            raise SandboxNotReachableError(sandbox, view.state)
        destination = SandboxDestination(owner=view.service_account, sandbox=view.name, sandbox_uid=view.uid)
        if destination not in self._clients:
            self._clients[destination] = self._service.runner(destination)
        return self._clients[destination]

    async def close(self) -> None:
        await self._service.close()
