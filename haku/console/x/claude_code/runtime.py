"""Claude Code's provider-specific Console runtime adapter.

Sandbox claims, runner bootstrap, bridge credentials, MCP credentials and attached-chat prompt
selection are Haku infrastructure owned by ``runtime.py`` / ``session_runtime.py``.  This adapter
only translates generic launch facts into Claude argv, speaks Claude's native protocol through the
runner, and projects Claude frames into the neutral conversation vocabulary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from haku.console.chat_models import RuntimeKind
from haku.console.x.claude_code import projection
from haku.console.x.claude_code.client import cli_over_websocket
from haku.console.x.conversation_events import ConversationEvent, Projection, ProjectionState
from haku.console.x.runtime import RuntimeClient, RuntimeClientFactory, RuntimeLaunch, TurnCompletion
from haku.runtime.x.bridge.client import FrameSink
from haku.runtime.x.bridge.options import ClaudeSession, HttpMcpServer, build_claude_launch
from haku.runtime.x.bridge.protocol import HarnessFrame, HarnessLaunch, TextWebSocket
from haku.runtime.x.bridge.transport import ProgressSink


@dataclass(frozen=True, slots=True)
class ClaudeRuntimeAdapter:
    """Claude launch/protocol/projection behavior, with no sandbox lifecycle state."""

    client_factory: RuntimeClientFactory = cli_over_websocket

    @property
    def kind(self) -> RuntimeKind:
        return RuntimeKind.CLAUDE_CODE

    @property
    def display_name(self) -> str:
        return "Claude"

    def build_launch(self, launch: RuntimeLaunch) -> HarnessLaunch:
        session = ClaudeSession(
            append_system_prompt=launch.appended_system_prompt,
            cwd=Path(launch.cwd),
            environment=launch.environment,
            mcp_servers={
                name: HttpMcpServer(
                    url=server.url, headers={"Authorization": f"Bearer {server.bearer_token.get_secret_value()}"}
                )
                for name, server in launch.mcp_servers.items()
            },
        )
        return build_claude_launch(session, resume_from=launch.resume_from)

    def client(
        self, websocket: TextWebSocket, launch: HarnessLaunch, progress: ProgressSink | None, frames_to: FrameSink
    ) -> RuntimeClient:
        return self.client_factory(websocket, launch, progress, frames_to)

    def project_frame(
        self, state: ProjectionState, *, frame_seq: int, frame: HarnessFrame
    ) -> tuple[ProjectionState, tuple[ConversationEvent, ...]]:
        folded, result = projection.project(
            state,
            [projection.RecordedFrame(frame_seq=frame_seq, payload=frame.frame)],
            delta_source=projection.DeltaSource.STREAM_EVENTS,
        )
        return folded, result.events

    def project_log(self, frames: Iterable[tuple[int, HarnessFrame]]) -> Projection:
        return projection.project_log(
            projection.RecordedFrame(frame_seq=seq, payload=frame.frame) for seq, frame in frames
        )

    @property
    def delta_frame_kind(self) -> str:
        return "stream_event"

    @property
    def prompt_frame_kinds(self) -> frozenset[str]:
        return frozenset({"user"})

    def complete_turn(self, frame: HarnessFrame) -> TurnCompletion:
        payload = frame.frame
        if payload.get("subtype") == "success":
            return TurnCompletion(final_text=str(payload.get("result") or "").strip())
        return TurnCompletion(
            final_text="",
            failure=(
                f"the agent's turn failed: {payload.get('subtype')}: {payload.get('stop_reason') or 'unknown error'}"
            ),
        )
