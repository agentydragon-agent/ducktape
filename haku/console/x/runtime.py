"""Backend-neutral Console runtime catalog.

The sandbox and runner lifecycle is Haku infrastructure.  A runtime registration pairs that generic
infrastructure with the one harness adapter that knows how to launch and speak a provider's native
protocol.  The runner itself remains one Pydantic-envelope process bridge for every harness.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import SecretStr

from haku.console.chat_models import RuntimeKind
from haku.console.x.conversation_events import ConversationEvent, Projection, ProjectionState
from haku.console.x.sandbox_claims import SandboxClaims
from haku.console.x.system_prompt import SystemPromptTemplate
from haku.runtime.x.bridge.client import FrameSink, ReceivedFrame, SentPrompt
from haku.runtime.x.bridge.protocol import HarnessFrame, HarnessLaunch, TextWebSocket
from haku.runtime.x.bridge.transport import ProgressSink


class RuntimeClient(Protocol):
    """The provider-neutral part of a connected harness client used by the turn loop."""

    async def connect(self) -> Mapping[str, Any]: ...

    async def query(self, text: str) -> SentPrompt: ...

    async def interrupt(self) -> None: ...

    def frames(self) -> AsyncIterator[ReceivedFrame]: ...

    async def wait_closed(self) -> None: ...

    async def aclose(self) -> None: ...


RuntimeClientFactory = Callable[[TextWebSocket, HarnessLaunch, ProgressSink | None, FrameSink], RuntimeClient]


@dataclass(frozen=True, slots=True)
class RuntimeLaunch:
    """Generic facts a harness launch builder translates into its native argv/configuration."""

    cwd: str
    environment: Mapping[str, str]
    mcp_servers: Mapping[str, RuntimeMcpServer]
    appended_system_prompt: str | None
    resume_from: int | None


@dataclass(frozen=True, slots=True)
class RuntimeMcpServer:
    """One explicitly configured MCP capability available to a native harness."""

    url: str
    bearer_token: SecretStr


@dataclass(frozen=True, slots=True)
class TurnCompletion:
    """Provider-neutral interpretation of the native frame that ended a turn."""

    final_text: str
    failure: str | None = None


class RuntimeAdapter(Protocol):
    """Provider-owned protocol behavior behind one immutable ``RuntimeKind``."""

    @property
    def kind(self) -> RuntimeKind: ...

    @property
    def display_name(self) -> str: ...

    def build_launch(self, launch: RuntimeLaunch) -> HarnessLaunch: ...

    def client(
        self, websocket: TextWebSocket, launch: HarnessLaunch, progress: ProgressSink | None, frames_to: FrameSink
    ) -> RuntimeClient: ...

    def project_frame(
        self, state: ProjectionState, *, frame_seq: int, frame: HarnessFrame
    ) -> tuple[ProjectionState, tuple[ConversationEvent, ...]]: ...

    def project_log(self, frames: Iterable[tuple[int, HarnessFrame]]) -> Projection: ...

    @property
    def delta_frame_kind(self) -> str: ...

    @property
    def prompt_frame_kinds(self) -> frozenset[str]: ...

    def complete_turn(self, frame: HarnessFrame) -> TurnCompletion: ...


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    """Generic runner/sandbox resources for one configured runtime implementation."""

    claims: SandboxClaims
    session_ttl_seconds: int
    cwd: str
    environment: Mapping[str, str]
    mcp_servers: Mapping[str, RuntimeMcpServer]
    system_prompt: SystemPromptTemplate


@dataclass(frozen=True, slots=True)
class ConfiguredRuntime:
    """One provider adapter paired with Haku-owned execution resources."""

    adapter: RuntimeAdapter
    resources: RuntimeResources


class UnsupportedRuntimeError(LookupError):
    """No adapter was registered for a conversation's immutable runtime kind."""


class RuntimeNotConfiguredError(RuntimeError):
    """A known runtime has no sandbox/credential configuration on this replica."""


class RuntimeRegistry:
    """Immutable runtime definitions plus the subset configured for execution.

    Read paths need only adapters.  A launch-capable Console registers resources separately for the
    same keys; absence is a registry fact rather than a half-initialized provider adapter.
    """

    def __init__(
        self,
        adapters: Mapping[RuntimeKind, RuntimeAdapter],
        resources: Mapping[RuntimeKind, RuntimeResources] | None = None,
    ):
        self._adapters = dict(adapters)
        self._resources = dict(resources or {})
        for kind, adapter in self._adapters.items():
            if adapter.kind is not kind:
                raise ValueError(f"runtime adapter key {kind!r} disagrees with adapter kind {adapter.kind!r}")
            if not adapter.prompt_frame_kinds:
                raise ValueError(f"runtime adapter {kind!r} declares no outbound prompt frame kind")
        unknown_resources = self._resources.keys() - self._adapters.keys()
        if unknown_resources:
            raise ValueError(f"runtime resources have no adapter: {sorted(kind.value for kind in unknown_resources)}")

    def adapter(self, kind: RuntimeKind) -> RuntimeAdapter:
        try:
            return self._adapters[kind]
        except KeyError as error:
            raise UnsupportedRuntimeError(f"runtime kind {kind!r} is not registered") from error

    def configured(self, kind: RuntimeKind) -> ConfiguredRuntime:
        adapter = self.adapter(kind)
        try:
            resources = self._resources[kind]
        except KeyError as error:
            raise RuntimeNotConfiguredError(f"runtime kind {kind!r} is not configured for execution") from error
        return ConfiguredRuntime(adapter=adapter, resources=resources)

    def __getitem__(self, kind: RuntimeKind) -> RuntimeAdapter:
        return self.adapter(kind)

    def __contains__(self, kind: RuntimeKind) -> bool:
        return kind in self._adapters

    @property
    def kinds(self) -> frozenset[RuntimeKind]:
        return frozenset(self._adapters)

    @property
    def configured_kinds(self) -> frozenset[RuntimeKind]:
        return frozenset(self._resources)

    async def aclose(self) -> None:
        """Close each configured claims client once, even if registrations share one."""
        closed: set[int] = set()
        for resources in self._resources.values():
            identity = id(resources.claims)
            if identity in closed:
                continue
            closed.add(identity)
            await resources.claims.aclose()
