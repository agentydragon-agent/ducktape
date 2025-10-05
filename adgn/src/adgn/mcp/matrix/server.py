"""Matrix MCP server with background inbox and yield semantics.

Features (MVP):
- Background sync watcher that collects new text messages in a single room
- Tools:
  - send_message(text) → post to room
  - drain_new_messages() → return and clear queued messages
  - yield(last_seen_event_id) → mark cursor and request end_turn via shared bus
- Emits ResourceUpdatedNotification on each new message via NotifyingFastMCP

Notes
- Designed for unencrypted rooms first. E2EE can be added via matrix-nio[e2e]
  and a persistent store_path, plus device verification. For now we avoid E2EE
  complexity and rely on plaintext rooms.
- Network credentials are supplied via MatrixConfig; the caller constructs this
  server in-proc via make_matrix_mcp().
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
import logging
from typing import Any, Callable

from nio import (  # type: ignore
    AsyncClient,
    LoginResponse,
    MatrixRoom,
    RoomMessageText,
)
from pydantic import BaseModel, Field

from adgn.agent.server.bus import ServerBus, UiEndTurn
from adgn.mcp._shared.fastmcp_helpers import mcp_flat_model
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP

# Matrix SDK uses millisecond timeouts for sync; keep constants explicit
SYNC_PRIME_TIMEOUT_MS = 1_000
SYNC_LOOP_TIMEOUT_MS = 30_000

logger = logging.getLogger(__name__)


class MatrixConfig(BaseModel):
    homeserver: str = Field(description="Base URL, e.g. https://matrix.example.com")
    user_id: str = Field(description="Matrix user id, e.g. @bot:example.com")
    access_token: str | None = Field(
        default=None, description="Access token for the device (preferred)"
    )
    password: str | None = Field(default=None, description="Password (fallback if no access token)")
    room: str = Field(
        description="Room id or alias to join/watch (e.g. !id:server or #alias:server)"
    )
    store_path: str | None = Field(
        default=None,
        description="Optional path for matrix-nio store (for E2EE / sessions)",
    )


class IncomingMessage(BaseModel):
    event_id: str
    room_id: str
    sender: str
    timestamp_ms: int
    body: str


class DrainResult(BaseModel):
    messages: list[IncomingMessage]
    last_event_id: str | None = None


class SendMessageInput(BaseModel):
    content: str = Field(description="Plaintext content to send to the room")


class YieldInput(BaseModel):
    last_seen_event_id: str = Field(
        description="The last event id the agent processed; used to advance cursor"
    )


@dataclass
class _Inbox:
    queue: list[IncomingMessage] = field(default_factory=list)
    new_event: asyncio.Event = field(default_factory=asyncio.Event)
    last_seen_event_id: str | None = None

    def enqueue(self, msg: IncomingMessage) -> None:
        self.queue.append(msg)
        # Signal that new messages are available
        if not self.new_event.is_set():
            self.new_event.set()

    def drain(self) -> DrainResult:
        if not self.queue:
            return DrainResult(messages=[], last_event_id=self.last_seen_event_id)
        msgs = list(self.queue)
        self.queue.clear()
        last_id = msgs[-1].event_id
        return DrainResult(messages=msgs, last_event_id=last_id)

    def ack(self, event_id: str) -> None:
        self.last_seen_event_id = event_id
        # If queue was drained and nothing new came in, lower the event to block next waiters
        if not self.queue and self.new_event.is_set():
            self.new_event.clear()


class _MatrixClient:
    """Thin wrapper for matrix-nio client with guarded imports."""

    def __init__(self, cfg: MatrixConfig, inbox: _Inbox, notify: Callable[[str], Any]):
        self.cfg = cfg
        self.inbox = inbox
        self._notify = notify
        self._client: AsyncClient | None = None  # set in start
        self._room_id: str | None = None
        self._bg_task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        self._client = AsyncClient(
            self.cfg.homeserver, self.cfg.user_id, store_path=self.cfg.store_path
        )
        c = self._client
        assert c is not None

        # Login if needed
        if self.cfg.access_token:
            c.access_token = self.cfg.access_token
            c.user_id = self.cfg.user_id
        else:
            if not self.cfg.password:
                raise RuntimeError("Matrix password or access_token required")
            res = await c.login(self.cfg.password)
            if not isinstance(res, LoginResponse):
                raise RuntimeError(f"Matrix login failed: {res}")

        # Ensure we're in the room
        room = self.cfg.room
        if room.startswith("#"):
            await c.join(room)
        # Resolve room id (for sending)
        await c.sync(timeout=SYNC_PRIME_TIMEOUT_MS)  # prime rooms
        rid = None
        for r in c.rooms.values():
            if (
                r.room_id == room
                or getattr(r, "display_name", None) == room
                or getattr(r, "canonical_alias", None) == room
            ):
                rid = r.room_id
                break
        if rid is None:
            # fallback: if looks like a room id, assume as-is
            rid = room
        self._room_id = rid

        # Callbacks for new messages
        def _on_message(room: MatrixRoom, event: RoomMessageText):  # type: ignore
            try:
                # Skip our own messages
                if event.sender == c.user:
                    return
                # Only text
                body = getattr(event, "body", None)
                if not isinstance(body, str):
                    return
                # server_timestamp is provided by nio; use getattr for SDK variation safety
                msg = IncomingMessage(
                    event_id=str(event.event_id),
                    room_id=str(room.room_id),
                    sender=str(event.sender),
                    timestamp_ms=int(getattr(event, "server_timestamp", 0)),
                    body=body,
                )
                self.inbox.enqueue(msg)
                # Emit a protocol notification so handlers can insert a system message
                try:
                    uri = f"matrix://inbox/{self._room_id}/{msg.event_id}"
                    # Fire and forget
                    asyncio.create_task(self._notify(uri))
                except Exception as e:
                    logger.warning("matrix notify failed: %s", e)
            except Exception as e:
                # Best effort; do not crash the callback
                logger.exception("matrix on_message callback failed: %s", e)

        c.add_event_callback(_on_message, (RoomMessageText,))

        async def _sync_forever() -> None:
            # Long-poll sync
            while True:
                try:
                    await c.sync(timeout=SYNC_LOOP_TIMEOUT_MS)
                except Exception:
                    logger.exception("matrix sync failed; retrying")
                    await asyncio.sleep(1.0)
                    continue

        self._bg_task = asyncio.create_task(_sync_forever())

    async def stop(self) -> None:
        c = self._client
        if c is None:
            return
        try:
            await c.close()
        except Exception as e:
            logger.warning("matrix client close failed", exc_info=e)
        t = self._bg_task
        if t:
            t.cancel()
            with suppress(Exception):  # type: ignore
                await t

    async def send_text(self, content: str) -> dict[str, Any]:
        c = self._client
        rid = self._room_id
        if c is None or rid is None:
            raise RuntimeError("Matrix client not started or room not resolved")
        res = await c.room_send(
            rid,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": content},
        )
        # nio returns a Response with event_id for successful send
        eid = getattr(res, "event_id", None)
        return {"ok": True, "event_id": eid}


def make_matrix_mcp(name: str, bus: ServerBus, cfg: MatrixConfig) -> NotifyingFastMCP:
    inbox = _Inbox()
    mcp = NotifyingFastMCP(
        name=name,
        instructions=(
            "Matrix bridge: receive new messages as notifications and use tools to\n"
            "interact. Contract: do not emit plain text; use matrix.send_message to\n"
            "reply and matrix.yield when finished. Start each turn by calling\n"
            "matrix.drain_new_messages to retrieve pending inbound messages."
        ),
    )

    # Background client managed via server lifespan; broadcast notifications on new msgs
    client_holder: dict[str, _MatrixClient] = {}

    async def _broadcast(uri: str) -> None:
        await mcp.broadcast_resource_updated(uri)

    # Lifespan wires the matrix-nio client
    @asynccontextmanager
    async def _lifespan(_: Any):
        mc = _MatrixClient(cfg, inbox, _broadcast)
        client_holder["client"] = mc
        await mc.start()
        try:
            yield
        finally:
            try:
                await mc.stop()
            except Exception as e:
                logger.debug("matrix client stop failed: %s", e)

    # Install lifespan on the underlying FastMCP server.
    # Exception: the upstream FastMCP currently exposes lifespan on the internal server
    # object; set via private attribute until a public hook is available.
    setattr(mcp._mcp_server, "lifespan", _lifespan)  # type: ignore[attr-defined]

    # Tools
    @mcp_flat_model(
        mcp,
        name="send_message",
        title="Send message",
        description="Send a plaintext message to the configured room",
        structured_output=True,
    )
    async def send_message(input: SendMessageInput) -> dict[str, Any]:
        mc = client_holder.get("client")
        if mc is None:
            return {"ok": False, "error": "matrix client not running"}
        try:
            return await mc.send_text(input.content)
        except Exception as e:  # pragmatic: return structured error
            return {"ok": False, "error": str(e)}

    @mcp_flat_model(
        mcp,
        name="drain_new_messages",
        title="Drain new messages",
        description="Return and clear queued inbound messages",
        structured_output=True,
    )
    def drain_new_messages() -> DrainResult:
        return inbox.drain()

    @mcp_flat_model(
        mcp,
        name="yield",
        title="Yield turn",
        description=("End the current turn and record the last seen event id."),
        structured_output=True,
    )
    def do_yield(input: YieldInput) -> UiEndTurn:
        inbox.ack(input.last_seen_event_id)
        bus.push_end_turn()
        return UiEndTurn()

    # Intentionally avoid setting dynamic attributes on the MCP wrapper; callers
    # should keep references to the returned inbox via closures or explicit state.
    return mcp
