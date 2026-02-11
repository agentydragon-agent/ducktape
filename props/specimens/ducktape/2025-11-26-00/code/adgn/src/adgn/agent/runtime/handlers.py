from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.handler import BaseHandler
from adgn.agent.notifications.types import NotificationsBatch
from adgn.agent.persist import Persistence
from adgn.agent.persist.handler import RunPersistenceHandler
from adgn.agent.reducer import NotificationsHandler
from adgn.agent.server.bus import ServerBus
from adgn.agent.server.mode_handler import ServerModeHandler
from adgn.agent.server.runtime import ConnectionManager


def build_handlers(
    *,
    poll_notifications: Callable[[], NotificationsBatch],
    manager: ConnectionManager,
    persistence: Persistence,
    get_run_id: Callable[[], UUID | None],
    ui_bus: ServerBus | None = None,
) -> tuple[list[BaseHandler], RunPersistenceHandler]:
    """Construct the standard handler stack for an agent.

    Returns (handlers, persist_handler).
    """
    persist_handler = RunPersistenceHandler(persistence=persistence, get_run_id=get_run_id)
    handlers: list[BaseHandler] = [manager, persist_handler]
    if ui_bus is not None:
        handlers.extend([ServerModeHandler(bus=ui_bus, poll_notifications=poll_notifications), DisplayEventsHandler()])
    else:
        # Production/non-UI path: flush MCP notifications via NotificationsHandler
        handlers.append(NotificationsHandler(poll_notifications))
    return handlers, persist_handler
