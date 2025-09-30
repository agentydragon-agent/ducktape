from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
import functools
from typing import Any, Callable, Protocol, cast
from weakref import WeakSet

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from pydantic import AnyUrl, TypeAdapter

from adgn.mcp._shared.fastmcp_helpers import FlatModelToolMixin, SafeDispatchServer

logger = logging.getLogger("adgn.mcp")

_ANY_URL: TypeAdapter[AnyUrl] = TypeAdapter(AnyUrl)


class _HasNameInstructions(Protocol):
    name: str
    instructions: str | None


class _CapturingServer(SafeDispatchServer):
    """Low-level Server that calls a hook when a ServerSession is created.

    This lets NotifyingFastMCP register the session as soon as initialize completes,
    so protocol notifications can be emitted before any request arrives.
    """

    def __init__(
        self,
        *a,
        on_session_created: "Callable[[ServerSession], None] | None" = None,
        **kw,
    ):
        super().__init__(*a, **kw)
        self._on_session_created = on_session_created

    async def run(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        initialization_options: InitializationOptions,
        raise_exceptions: bool = False,
        stateless: bool = False,
    ):
        # Leverage SafeDispatchServer.run but intercept the moment the session is created.
        async with AsyncExitStack() as stack:
            lifespan_context = await stack.enter_async_context(self.lifespan(self))
            session = await stack.enter_async_context(
                ServerSession(
                    read_stream,
                    write_stream,
                    initialization_options,
                    stateless=stateless,
                )
            )
            if self._on_session_created:
                self._on_session_created(session)
            async with anyio.create_task_group() as tg:
                async for message in session.incoming_messages:
                    tg.start_soon(
                        self._handle_message,
                        message,
                        session,
                        lifespan_context,
                        raise_exceptions,
                    )


class NotifyingFastMCP(FlatModelToolMixin, FastMCP):
    """FastMCP subclass that can broadcast protocol notifications outside requests.

    - Captures live ServerSession objects lazily on first tool invocation
    - Provides broadcast_resource_updated(uri) to emit ResourceUpdatedNotification to all sessions
    - Queues URIs when no sessions exist yet (flushed on first broadcast once a session is present)
    - No monkeypatching: uses standard FastMCP.get_context() inside a thin tool wrapper

    TODO(mpokorny): Consider wrapping the low-level Server.run to capture ServerSession
    at initialize time (immediately after creation) to avoid relying on first-request
    capture via list_tools/list_resources/tool wrappers.
    """

    def __init__(self, name: str, *, instructions: str | None = None) -> None:
        super().__init__(name=name, instructions=instructions)
        self._sessions: WeakSet[ServerSession] = WeakSet()
        self._pending_uris: list[str] = []
        # Replace the low-level server with a capturing variant and re-register handlers
        server = cast(_HasNameInstructions, self._mcp_server)
        name0 = server.name
        instr0 = server.instructions

        async def _on_created(sess: ServerSession) -> None:
            # Register and flush any queued notifications
            self._sessions.add(sess)
            await self.flush_pending()

        # Wrap in a small adapter because low-level server expects a sync callable
        def _adapter(sess: ServerSession) -> None:
            # Worst-case: ensure the captured session is the correct low-level type
            assert isinstance(sess, ServerSession)
            asyncio.create_task(_on_created(sess))

        capturing_server = _CapturingServer(
            name=name0,
            instructions=instr0,
            on_session_created=_adapter,
        )
        # Help mypy understand the concrete type of the low-level server
        self._mcp_server: SafeDispatchServer = cast(
            SafeDispatchServer, capturing_server
        )
        # Re-install FastMCP handlers on the new low-level server
        self._setup_handlers()

    # ---- Capture current session when inside a request ----
    def _capture_session_if_any(self) -> None:
        ctx = self.get_context()
        rc = getattr(ctx, "request_context", None)
        if rc is None or rc.session is None:
            return
        sess = rc.session  # low-level ServerSession
        if sess not in self._sessions:
            self._sessions.add(sess)

    # Wrap tools to auto-capture a session when tools run
    def tool(self, *args: Any, **kwargs: Any):
        base_decorator = super().tool(*args, **kwargs)

        def _decorator(fn):
            @functools.wraps(fn)
            async def _wrapped(*a, **kw):
                result = await fn(*a, **kw)
                # Capture after handler ran to ensure request_context is populated
                self._capture_session_if_any()
                await self.flush_pending()
                return result

            return base_decorator(_wrapped)

        return _decorator

    async def list_tools(self) -> Any:
        res = await super().list_tools()
        self._capture_session_if_any()
        await self.flush_pending()
        return res

    async def list_resources(self) -> Any:
        res = await super().list_resources()
        self._capture_session_if_any()
        await self.flush_pending()
        return res

    # ---- Broadcast API (can be called outside request scope) ----
    async def broadcast_resource_updated(self, uri: str) -> None:
        # If no sessions yet, queue and return
        sessions = [s for s in list(self._sessions) if s is not None]
        if not sessions:
            self._pending_uris.append(uri)
            return
        # Send to all current sessions; prune failures

        logger.debug(
            "broadcast_resource_updated: uri=%s sessions=%d", uri, len(sessions)
        )
        uri_value = _ANY_URL.validate_python(uri)
        send_tasks = [s.send_resource_updated(uri_value) for s in sessions]
        results = await asyncio.gather(*send_tasks, return_exceptions=True)
        logger.debug("broadcast done: results=%s", [repr(r) for r in results])
        # Best-effort: drop sessions that errored
        for s, r in zip(sessions, results):
            if isinstance(r, Exception):
                logger.warning("send_resource_updated failed: %s", r)
                try:
                    self._sessions.discard(s)
                except Exception:
                    pass

    async def flush_pending(self) -> None:
        """Send any queued URIs to current sessions (if any)."""
        if not self._pending_uris:
            return
        sessions = [s for s in list(self._sessions) if s is not None]
        if not sessions:
            return
        uris = self._pending_uris[:]
        self._pending_uris.clear()
        # send each queued URI to all sessions
        await asyncio.gather(
            *[
                s.send_resource_updated(_ANY_URL.validate_python(uri))
                for s in sessions
                for uri in uris
            ],
            return_exceptions=True,
        )
