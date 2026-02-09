"""Grader supervisor - manages per-snapshot grader lifecycle.

Supervises one grader container per snapshot:
- Defers initial spawning until HTTP backend is ready (avoids self-referencing
  image resolution during lifespan)
- Listens for pg_notify on snapshot_created to spawn new graders
- Listens for pg_notify on grader_definition_changed to restart all graders
  when the grader image tag moves (e.g. new image pushed)

Each grader runs eternally inside its container, handling context exhaustion
internally. Host-side we supervise container lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import TYPE_CHECKING, Any

import asyncpg
import httpx
from asyncpg.pool import PoolConnectionProxy

from props.agents.grader.notifications import (
    GRADER_DEFINITION_CHANGED_CHANNEL,
    SNAPSHOT_CREATED_CHANNEL,
    GraderDefinitionChangedNotification,
    SnapshotCreatedNotification,
)
from props.core.ids import SnapshotSlug
from props.db.config import DatabaseConfig
from props.db.database import Database
from props.db.models import Snapshot

if TYPE_CHECKING:
    from props.orchestration.agent_registry import AgentRegistry

logger = logging.getLogger(__name__)


class GraderSupervisor:
    """Manages per-snapshot grader containers.

    Each snapshot gets one long-lived grader container. Graders sleep when
    no drift and wake on pg_notify. Context exhaustion is handled inside
    the container via transcript summarization.

    Use as async context manager for proper lifecycle:

        async with GraderSupervisor(...) as gs:
            await some_long_running_task()
        # gs.shutdown() called automatically
    """

    def __init__(self, registry: AgentRegistry, db_config: DatabaseConfig, model: str, db: Database, backend_url: str):
        self._registry = registry
        self._db_config = db_config
        self._model = model
        self._db = db
        self._backend_url = backend_url
        self._tasks: dict[SnapshotSlug, asyncio.Task[Any]] = {}
        self._listener_conn: asyncpg.Connection[Any] | None = None
        self._startup_task: asyncio.Task[Any] | None = None
        self._shutdown = False

    async def __aenter__(self) -> GraderSupervisor:
        await self.start()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        await self.shutdown()

    def _snapshot_created_callback(
        self, connection: asyncpg.Connection[Any] | PoolConnectionProxy[Any], pid: int, channel: str, payload: object
    ) -> None:
        """Handle incoming pg_notify notifications for snapshot creation."""
        if self._shutdown:
            return

        if not isinstance(payload, str):
            logger.error(f"pg_notify payload is not a string: {type(payload)}")
            return

        notification = SnapshotCreatedNotification.model_validate_json(payload)

        slug = notification.snapshot_slug
        if slug in self._tasks and not self._tasks[slug].done():
            logger.debug(f"Grader for {slug} already running, ignoring notification")
            return

        logger.info(f"Snapshot created: {slug}, spawning grader")
        self._tasks[slug] = asyncio.create_task(self._run_grader(slug), name=f"grader-{slug}")

    def _grader_definition_changed_callback(
        self, connection: asyncpg.Connection[Any] | PoolConnectionProxy[Any], pid: int, channel: str, payload: object
    ) -> None:
        """Handle grader tag push — restart all graders to pick up the new image."""
        if self._shutdown:
            return

        if not isinstance(payload, str):
            logger.error(f"pg_notify payload is not a string: {type(payload)}")
            return

        notification = GraderDefinitionChangedNotification.model_validate_json(payload)
        logger.info(f"Grader definition changed: {notification.tag} -> {notification.digest}")

        # Cancel running graders and restart all with the new image
        for slug, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
            self._tasks[slug] = asyncio.create_task(self._run_grader(slug), name=f"grader-{slug}")

        logger.info(f"Restarted {len(self._tasks)} graders after definition change")

    async def start(self) -> None:
        """Start listening for notifications and schedule deferred grader spawning.

        Sets up pg_notify listeners immediately (during lifespan), then spawns a
        background task that waits for the HTTP server to be ready before starting
        grader containers. This avoids the chicken-and-egg problem where containers
        need the registry proxy (served by the same HTTP server) to resolve images.
        """
        # Start listener first so we don't miss any notifications during startup
        await self._start_listener()

        # Defer container spawning until HTTP server is ready
        self._startup_task = asyncio.create_task(self._deferred_spawn(), name="grader-startup")

    async def _wait_for_backend(self) -> None:
        """Poll the backend health endpoint until it responds."""
        health_url = f"{self._backend_url}/health"
        async with httpx.AsyncClient() as client:
            while not self._shutdown:
                try:
                    resp = await client.get(health_url, timeout=2.0)
                    if resp.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)

    async def _deferred_spawn(self) -> None:
        """Wait for HTTP server, then spawn graders for all existing snapshots."""
        try:
            await self._wait_for_backend()
        except asyncio.CancelledError:
            return

        if self._shutdown:
            return

        with self._db.session() as session:
            snapshots = session.query(Snapshot.slug).all()
            snapshot_slugs = [s.slug for s in snapshots]

        if snapshot_slugs:
            logger.info(f"Starting graders for {len(snapshot_slugs)} existing snapshots")
            for slug in snapshot_slugs:
                self._tasks[slug] = asyncio.create_task(self._run_grader(slug), name=f"grader-{slug}")
        else:
            logger.info("No existing snapshots, listening for new ones via pg_notify")

    async def _start_listener(self) -> None:
        """Start listening for snapshot_created and grader_definition_changed notifications."""
        self._listener_conn = await self._db_config.asyncpg_connect()
        await self._listener_conn.add_listener(SNAPSHOT_CREATED_CHANNEL, self._snapshot_created_callback)
        await self._listener_conn.add_listener(
            GRADER_DEFINITION_CHANGED_CHANNEL, self._grader_definition_changed_callback
        )
        logger.info(f"Listening on channels '{SNAPSHOT_CREATED_CHANNEL}', '{GRADER_DEFINITION_CHANGED_CHANNEL}'")

    async def _stop_listener(self) -> None:
        """Stop the notification listeners."""
        if self._listener_conn:
            try:
                await self._listener_conn.remove_listener(SNAPSHOT_CREATED_CHANNEL, self._snapshot_created_callback)
                await self._listener_conn.remove_listener(
                    GRADER_DEFINITION_CHANGED_CHANNEL, self._grader_definition_changed_callback
                )
                await self._listener_conn.close()
            except Exception as e:
                logger.warning(f"Error closing listener connection: {e}")
            self._listener_conn = None

    async def _run_grader(self, snapshot_slug: SnapshotSlug) -> None:
        """Run grader container for a snapshot. Runs indefinitely until cancelled."""
        try:
            logger.info(f"Starting grader for {snapshot_slug}")
            await self._registry.run_snapshot_grader(snapshot_slug=snapshot_slug, model=self._model)
            logger.info(f"Grader for {snapshot_slug} exited")
        except asyncio.CancelledError:
            logger.info(f"Grader for {snapshot_slug} cancelled")
            raise
        except Exception:
            logger.exception(f"Grader for {snapshot_slug} failed")

    async def shutdown(self) -> None:
        """Signal all graders to shutdown and wait for completion."""
        self._shutdown = True
        logger.info("Shutting down graders...")

        # Stop listener first
        await self._stop_listener()

        # Cancel startup task if still running
        if self._startup_task and not self._startup_task.done():
            self._startup_task.cancel()

        # Cancel all tasks
        for task in self._tasks.values():
            if not task.done():
                task.cancel()

        # Wait for all to complete
        all_tasks = list(self._tasks.values())
        if self._startup_task:
            all_tasks.append(self._startup_task)
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)

        logger.info("All graders stopped")
