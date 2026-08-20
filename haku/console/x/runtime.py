"""Backend-neutral console runtime seam.

A conversation is pinned to one ``RuntimeKind`` for its whole lifetime.  This module owns the
small registry that turns that durable discriminator into the implementation which knows how to
launch a runner, inspect its sandbox, and project native frames.  Provider-specific code belongs in
its adapter module; the session loop only consumes this interface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from typing import Any, Protocol
from uuid import UUID

from haku.console.chat_models import RuntimeKind
from haku.console.x.claude_code.runtime import ClaudeRuntimeAdapter
from haku.console.x.conversation_events import Projection, ProjectionState
from haku.console.x.sandbox_claims import SandboxClaims
from haku.console.x.system_prompt import SystemPromptTemplate
from haku.runtime.x.bridge.cli_client import FrameSink, ReceivedFrame, SentPrompt
from haku.runtime.x.bridge.protocol import HarnessLaunch, TextWebSocket


class RuntimeClient(Protocol):
    """The provider-neutral part of a connected runtime client used by the turn loop."""

    async def connect(self) -> Mapping[str, Any]: ...

    async def query(self, text: str) -> SentPrompt: ...

    async def interrupt(self) -> None: ...

    def frames(self) -> AsyncIterator[ReceivedFrame]: ...

    async def wait_closed(self) -> None: ...

    async def aclose(self) -> None: ...


class RuntimeAdapter(Protocol):
    """One concrete runtime implementation, selected by ``Conversation.runtime_kind``."""

    @property
    def kind(self) -> RuntimeKind: ...

    @property
    def display_name(self) -> str: ...

    @property
    def session_ttl_seconds(self) -> int: ...

    @property
    def cwd(self) -> str: ...

    @property
    def system_prompt(self) -> SystemPromptTemplate | None: ...

    async def create_sandbox(self, *, session_id: UUID, bridge_token: str, expires_at: Any) -> None: ...

    async def renew_sandbox(self, *, session_id: UUID, expires_at: Any) -> None: ...

    async def delete_sandbox(self, *, session_id: UUID) -> None: ...

    async def inspect_sandbox(self, *, session_id: UUID) -> Any: ...

    async def close(self) -> None: ...

    def provisioning_error(self, session_id: UUID, error: str) -> Any: ...

    def build_launch(self, *, appended_system_prompt: str | None, resume_from: int | None) -> HarnessLaunch: ...

    def client(
        self, websocket: TextWebSocket, launch: HarnessLaunch, progress: Any, frames_to: FrameSink
    ) -> RuntimeClient: ...

    def project_frame(
        self, state: ProjectionState, *, frame_seq: int, payload: dict[str, Any]
    ) -> tuple[ProjectionState, tuple[Any, ...]]: ...

    def project_log(self, frames: Iterable[tuple[int, dict[str, Any]]]) -> Projection: ...

    @property
    def delta_frame_kind(self) -> str: ...

    @property
    def prompt_frame_kinds(self) -> frozenset[str]: ...

    def turn_failed(self, payload: Mapping[str, Any]) -> bool: ...

    def turn_failure_message(self, payload: Mapping[str, Any]) -> str: ...


class UnsupportedRuntimeError(LookupError):
    """No adapter was registered for a conversation's immutable runtime kind."""


class RuntimeRegistry:
    """Immutable runtime adapter catalog.

    The mapping is deliberately keyed by the application enum rather than by a user-controlled
    string.  Registration validates that each adapter agrees with its key, and lookup fails closed
    for an unregistered kind rather than silently selecting Claude.
    """

    def __init__(self, adapters: Mapping[RuntimeKind, RuntimeAdapter]):
        self._adapters = dict(adapters)
        for kind, adapter in self._adapters.items():
            if adapter.kind is not kind:
                raise ValueError(f"runtime adapter key {kind!r} disagrees with adapter kind {adapter.kind!r}")
            if not adapter.prompt_frame_kinds:
                raise ValueError(f"runtime adapter {kind!r} declares no outbound prompt frame kind")

    def get(self, kind: RuntimeKind) -> RuntimeAdapter:
        try:
            return self._adapters[kind]
        except KeyError as error:
            raise UnsupportedRuntimeError(f"runtime kind {kind!r} is not registered") from error

    def __getitem__(self, kind: RuntimeKind) -> RuntimeAdapter:
        return self.get(kind)

    def __contains__(self, kind: RuntimeKind) -> bool:
        return kind in self._adapters

    @property
    def kinds(self) -> frozenset[RuntimeKind]:
        return frozenset(self._adapters)

    @classmethod
    def projection_only(cls) -> RuntimeRegistry:
        """Build the read-path catalog used by stores that predate runtime injection.

        The production catalog is composed with deploy configuration in ``app.py``.  Read-only
        helpers such as re-projection need only the Claude reducer and therefore use this narrow
        catalog when no service registry was supplied (all currently stored conversations are
        Claude conversations).
        """
        return cls({RuntimeKind.CLAUDE_CODE: ClaudeRuntimeAdapter.for_projection()})


def legacy_claude_registry(
    config: Any,
    claims: SandboxClaims,
    *,
    mcp_token: Any,
    system_prompt: SystemPromptTemplate | None,
    client_factory: Any = None,
) -> RuntimeRegistry:
    """Compatibility constructor for existing tests and callers.

    The old ``SessionService(config, ..., claims=...)`` shape remains accepted while the
    composition root moves to an explicit registry.
    """
    adapter = ClaudeRuntimeAdapter(
        config, claims, mcp_token=mcp_token, system_prompt=system_prompt, client_factory=client_factory
    )
    return RuntimeRegistry({RuntimeKind.CLAUDE_CODE: adapter})


def claude_registry(
    config: Any, claims: SandboxClaims, *, mcp_token: Any, system_prompt: SystemPromptTemplate | None
) -> RuntimeRegistry:
    """Compose the currently supported production catalog: Claude only."""
    return legacy_claude_registry(config, claims, mcp_token=mcp_token, system_prompt=system_prompt)
