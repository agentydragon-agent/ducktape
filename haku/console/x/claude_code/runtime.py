"""Claude Code's Console runtime adapter.

Everything in this module is provider wiring: Claude's launch arguments, native frame reducer,
control client, failure envelope, and Claude sandbox implementation.  The session loop imports only
the backend-neutral ``RuntimeAdapter`` protocol and selects this adapter through ``RuntimeRegistry``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from haku.console.chat_models import RuntimeKind
from haku.console.config import ClaudeRuntimeConfig
from haku.console.x.claude_code import projection
from haku.console.x.conversation_events import Projection, ProjectionState
from haku.console.x.sandbox_claims import ProvisioningStep, SandboxClaims, provisioning_view
from haku.console.x.system_prompt import SystemPromptTemplate
from haku.runtime.x.bridge.cli_client import FrameSink, cli_over_websocket
from haku.runtime.x.bridge.options import ClaudeSession, HttpMcpServer, build_claude_launch
from haku.runtime.x.bridge.protocol import HarnessLaunch, TextWebSocket


def _native_payload(frame: Mapping[str, Any]) -> dict[str, Any] | None:
    """Claude's native JSON from the complete inner harness frame, or None when it is not Claude.

    The bridge and frame log preserve the complete inner frame. Runtime adapters own the one
    provider-specific unwrap needed for interpretation; neutral read/execution paths must never
    flatten it or silently fall back to Claude.
    """
    payload = frame.get("payload")
    return payload if frame.get("kind") == "claude" and isinstance(payload, dict) else None


@dataclass(frozen=True, slots=True)
class ClaudeRuntimeAdapter:
    """The one production Console runtime currently registered."""

    config: ClaudeRuntimeConfig | None = None
    claims: SandboxClaims | None = None
    mcp_token: SecretStr | None = None
    system_prompt: SystemPromptTemplate | None = None
    client_factory: Any = None

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.CLAUDE_CODE

    @property
    def display_name(self) -> str:
        return "Claude"

    @property
    def session_ttl_seconds(self) -> int:
        return self._required_config.session_ttl_seconds

    @property
    def cwd(self) -> str:
        return self._required_config.cwd

    @property
    def _required_config(self) -> ClaudeRuntimeConfig:
        if self.config is None:
            raise RuntimeError("Claude runtime lifecycle configuration is unavailable")
        return self.config

    @property
    def _required_claims(self) -> SandboxClaims:
        if self.claims is None:
            raise RuntimeError("Claude runtime sandbox claims are unavailable")
        return self.claims

    @property
    def _required_mcp_token(self) -> SecretStr:
        if self.mcp_token is None:
            raise RuntimeError("Claude runtime MCP token is unavailable")
        return self.mcp_token

    async def create_sandbox(self, *, session_id: UUID, bridge_token: str, expires_at: datetime) -> None:
        await self._required_claims.create(session_id=session_id, bridge_token=bridge_token, expires_at=expires_at)

    async def renew_sandbox(self, *, session_id: UUID, expires_at: datetime) -> None:
        await self._required_claims.renew(session_id=session_id, expires_at=expires_at)

    async def delete_sandbox(self, *, session_id: UUID) -> None:
        await self._required_claims.delete(session_id=session_id)

    async def inspect_sandbox(self, *, session_id: UUID) -> Any:
        return await self._required_claims.inspect(session_id=session_id)

    async def close(self) -> None:
        if self.claims is not None:
            await self.claims.aclose()

    def provisioning_error(self, session_id: UUID, error: str) -> Any:
        return provisioning_view(
            f"claude-{session_id.hex}", step=ProvisioningStep.CLAIM_CREATED, observation_error=error
        )

    def build_launch(self, *, appended_system_prompt: str | None, resume_from: int | None) -> HarnessLaunch:
        config = self._required_config
        token = self._required_mcp_token
        session = ClaudeSession(
            append_system_prompt=appended_system_prompt,
            cwd=Path(config.cwd),
            environment=config.claude_environment(),
            mcp_servers={
                "haku-console": HttpMcpServer(
                    url=config.mcp_url, headers={"Authorization": f"Bearer {token.get_secret_value()}"}
                )
            },
        )
        return build_claude_launch(session, resume_from=resume_from)

    def client(self, websocket: TextWebSocket, launch: HarnessLaunch, progress: Any, frames_to: FrameSink) -> Any:
        factory = self.client_factory or cli_over_websocket
        return factory(websocket, launch, progress, frames_to)

    def project_frame(
        self, state: ProjectionState, *, frame_seq: int, payload: dict[str, Any]
    ) -> tuple[ProjectionState, tuple[Any, ...]]:
        # Native evidence stays readable even when a future/unknown frame has no Claude `type`.
        # It says nothing in Claude's neutral vocabulary; the whole-log view below reports it as
        # unprojected rather than letting provider interpretation break forensic reads.
        if not isinstance(payload.get("type"), str):
            return state, ()
        folded, result = projection.project(
            state,
            [projection.RecordedFrame(frame_seq=frame_seq, payload=payload)],
            delta_source=projection.DeltaSource.STREAM_EVENTS,
        )
        return folded, result.events

    def project_log(self, frames: Iterable[tuple[int, dict[str, Any]]]) -> Projection:
        native: list[projection.RecordedFrame] = []
        opaque: Counter[str] = Counter()
        for seq, frame in frames:
            payload = _native_payload(frame)
            if payload is None:
                kind = frame.get("kind")
                opaque[f"<unexpected-harness-frame:{kind if isinstance(kind, str) else 'undiscriminated'}>"] += 1
            elif isinstance(payload.get("type"), str):
                native.append(projection.RecordedFrame(frame_seq=seq, payload=payload))
            else:
                discriminator = payload.get("method")
                opaque[discriminator if isinstance(discriminator, str) else "<undiscriminated>"] += 1
        projected = projection.project_log(native)
        return Projection(
            events=projected.events, unprojected=MappingProxyType(dict(Counter(projected.unprojected) + opaque))
        )

    @property
    def delta_frame_kind(self) -> str:
        return "stream_event"

    @property
    def prompt_frame_kinds(self) -> frozenset[str]:
        return frozenset({"user"})

    def turn_failed(self, payload: Mapping[str, Any]) -> bool:
        return payload.get("subtype") != "success"

    def turn_failure_message(self, payload: Mapping[str, Any]) -> str:
        return f"the agent's turn failed: {payload.get('subtype')}: {payload.get('stop_reason') or 'unknown error'}"

    @classmethod
    def for_projection(cls) -> ClaudeRuntimeAdapter:
        """A config-free adapter for read-only projection paths."""
        return cls()
