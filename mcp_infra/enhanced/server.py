from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastmcp.server import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.server.low_level import LowLevelServer
from fastmcp.server.middleware.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types as mcp_types
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.session import ServerSession

from mcp_infra.enhanced.flat_mixin import FlatModelMixin
from mcp_infra.enhanced.oob_notify_mixin import NotificationsMixin
from mcp_infra.enhanced.openai_strict_mixin import OpenAIStrictModeMixin

logger = logging.getLogger(__name__)


class _CapabilitiesServer(LowLevelServer):
    """LowLevelServer with extended capabilities.

    Adds:
    - Merge custom experimental capabilities into initialization
    - Advertise resources.subscribe when a handler is registered
    """

    def __init__(
        self, fastmcp: FastMCP, *a: Any, experimental_capabilities: dict[str, dict[str, Any]] | None = None, **kw: Any
    ):
        super().__init__(fastmcp, *a, **kw)
        self._experimental_capabilities = experimental_capabilities or {}

    def create_initialization_options(
        self,
        notification_options: NotificationOptions | None = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        **kwargs: Any,
    ):
        caps = dict(experimental_capabilities or {})
        for group, values in (self._experimental_capabilities or {}).items():
            merged = dict(caps.get(group) or {})
            merged.update(values or {})
            caps[group] = merged
        return super().create_initialization_options(
            notification_options=notification_options, experimental_capabilities=caps, **kwargs
        )

    def get_capabilities(
        self, notification_options: NotificationOptions, experimental_capabilities: dict[str, dict[str, Any]]
    ):
        caps = super().get_capabilities(notification_options, experimental_capabilities)
        if mcp_types.SubscribeRequest in self.request_handlers:
            if caps.resources is None:
                caps.resources = mcp_types.ResourcesCapability()
            caps.resources.subscribe = True
        return caps


class _SessionCapturingMiddleware(Middleware):
    """Middleware that captures ServerSession on initialization.

    Uses v3's on_initialize hook to register sessions for out-of-band notifications.
    """

    def __init__(self, enhanced: EnhancedFastMCP) -> None:
        self._enhanced = enhanced

    async def on_initialize(
        self,
        context: MiddlewareContext[mcp_types.InitializeRequest],
        call_next: CallNext[mcp_types.InitializeRequest, mcp_types.InitializeResult | None],
    ) -> mcp_types.InitializeResult | None:
        result = await call_next(context)
        # Capture the session after successful initialization
        if context.fastmcp_context is not None and context.fastmcp_context.session is not None:
            session = context.fastmcp_context.session
            if isinstance(session, ServerSession):
                self._enhanced._sessions.add(session)
                await self._enhanced.flush_pending()
        return result


class EnhancedFastMCP(OpenAIStrictModeMixin, FlatModelMixin, NotificationsMixin, FastMCP):
    """Batteries-included FastMCP composed from 3 mixins.

    Composition:
    - OpenAIStrictModeMixin: Validates tool schemas at registration time
    - FlatModelMixin: ValidationError formatting + .flat_model() convenience
    - NotificationsMixin: Out-of-band broadcast methods
    - Plus: Session capturing via middleware (v3 on_initialize hook)
    - Plus: Experimental capabilities support via _CapabilitiesServer

    Features:
    - Session capturing & out-of-band notification broadcasts
    - Structured ValidationError formatting (for flat-model tools)
    - OpenAI strict mode schema validation (unconditional)
    - Auto-advertise subscribe capability
    - Experimental capabilities support
    - .flat_model() convenience method
    """

    _mcp_server: LowLevelServer

    def __init__(
        self,
        name: str | None = None,
        *,
        instructions: str | None = None,
        lifespan: Callable[[FastMCP], AbstractAsyncContextManager[object]] | None = None,
        experimental_capabilities: dict[str, dict[str, object]] | None = None,
        auth: AuthProvider | None = None,
        version: str | None = None,
    ) -> None:
        super().__init__(name=name, instructions=instructions, lifespan=lifespan, auth=auth, version=version)
        self._experimental_capabilities = experimental_capabilities or {}

        # Add session-capturing middleware
        self.middleware.append(_SessionCapturingMiddleware(self))

        # Replace LowLevelServer with capabilities-enhanced variant
        capabilities_server = _CapabilitiesServer(
            self,
            name=self.name,
            instructions=self.instructions,
            lifespan=self._mcp_server.lifespan,
            experimental_capabilities=self._experimental_capabilities,
            version=version,
        )
        self._mcp_server = capabilities_server
        self._setup_handlers()
