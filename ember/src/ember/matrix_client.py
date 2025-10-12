from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from nio import AsyncClient, RoomMessageText
from nio.events.invite_events import InviteMemberEvent
from nio.responses import (
    InviteInfo,
    JoinedRoomsError,
    JoinedRoomsResponse,
    JoinError,
    SyncError,
    SyncResponse,
    WhoamiError,
    WhoamiResponse,
)

from .config import MatrixSettings

logger = logging.getLogger(__name__)


class MatrixClient:
    """Matrix client that streams new room messages via an async queue."""

    def __init__(self, settings: MatrixSettings, debounce_seconds: float = 0.5) -> None:
        self._settings = settings
        self._client: AsyncClient | None = None
        self._since: str | None = None
        self._state_store = settings.state_store
        self._user_id: str | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._queue: asyncio.Queue[RoomMessageText] = asyncio.Queue()
        self._debounce = max(debounce_seconds, 0.1)
        self._control_rooms: set[str] = set()
        self._token_secret = settings.access_token_secret
        self._active_access_token: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self._settings.base_url and self._token_secret.value())

    async def start(self) -> None:
        if not self.configured:
            raise RuntimeError("Matrix client is not configured correctly")
        if self._sync_task and not self._sync_task.done():
            return

        logger.info("Starting Matrix client for homeserver %s", self._settings.base_url)

        self._since = None
        self._queue = asyncio.Queue()
        self._client = await self._create_client()
        self._control_rooms = await self._initialise_control_rooms()
        self._since = self._load_since_token()

        logger.info(
            "Initialized Matrix client; tracking %d joined rooms: %s",
            len(self._control_rooms),
            ", ".join(sorted(self._control_rooms)) or "(none)",
        )

        self._stop_event.clear()
        self._sync_task = asyncio.create_task(self._sync_loop(), name="matrix-sync-loop")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._sync_task is not None:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._active_access_token = None

    async def close(self) -> None:
        await self.stop()

    async def get_events(self, timeout: float = 60.0) -> list[RoomMessageText]:
        """Wait for a batch of new events (debounced)."""

        try:
            first = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return []

        events = [first]
        # Debounce to accumulate events that land together
        await asyncio.sleep(self._debounce)
        while not self._queue.empty():
            events.append(self._queue.get_nowait())
        return events

    async def _initialise_control_rooms(self) -> set[str]:
        assert self._client is not None
        return await self._fetch_joined_rooms()

    async def _fetch_joined_rooms(self) -> set[str]:
        assert self._client is not None
        try:
            response = await self._client.joined_rooms()
        except Exception as exc:  # noqa: BLE001 - keep startup alive
            logger.warning("Failed to fetch joined rooms: %s", exc)
            return set()

        if isinstance(response, JoinedRoomsError):
            logger.warning("Matrix joined_rooms error: %s", response.message)
            return set()
        if not isinstance(response, JoinedRoomsResponse):
            logger.warning("Unexpected joined_rooms response: %r", response)
            return set()
        return set(response.rooms or [])

    async def _sync_loop(self) -> None:
        assert self._client is not None
        try:
            while not self._stop_event.is_set():
                if (response := await self._sync_once()) is None:
                    await asyncio.sleep(5)
                    continue

                logger.debug(
                    "Matrix sync succeeded; next_batch=%s, joined=%d, invite=%d, leave=%d",
                    response.next_batch,
                    len(response.rooms.join or {}),
                    len(response.rooms.invite or {}),
                    len(response.rooms.leave or {}),
                )

                self._since = response.next_batch
                self._persist_since_token(response.next_batch)
                await self._handle_invites(response)
                await self._handle_joined_rooms(response)
                await self._handle_left_rooms(response)
        except asyncio.CancelledError:
            raise

    async def _handle_invites(self, response: SyncResponse) -> None:
        if not (invites := response.rooms.invite):
            return

        for room_id, invite in invites.items():
            if await self._should_accept_invite(room_id, invite):
                await self._accept_invite(room_id)

    async def _handle_joined_rooms(self, response: SyncResponse) -> None:
        joined = response.rooms.join or {}
        for room_id, room in joined.items():
            timeline = room.timeline.events or []
            logger.debug(
                "Matrix room %s timeline has %d events (limited=%s)",
                room_id,
                len(timeline),
                room.timeline.limited if room.timeline else None,
            )
            last_event_id: str | None = None
            for event in timeline:
                if isinstance(event, RoomMessageText):
                    await self._queue.put(event)
                    last_event_id = event.event_id
                    body = event.body
                    if not isinstance(body, str):
                        body = str(body)
                    logger.info("[matrix] room=%s sender=%s event=%s: %s", room_id, event.sender, event.event_id, body)
                else:
                    logger.debug(
                        "Matrix room %s ignoring event type=%s from %s",
                        room_id,
                        type(event).__name__,
                        getattr(event, "sender", "unknown"),
                    )

            if last_event_id is not None:
                await self._mark_read(room_id, last_event_id)

    async def _handle_left_rooms(self, response: SyncResponse) -> None:
        if not (left := response.rooms.leave):
            return
        if not (removed := set(left) & self._control_rooms):
            return
        self._control_rooms.difference_update(removed)
        for room_id in removed:
            logger.info("Removed control room %s after leave", room_id)

    async def set_typing(self, room_ids: Iterable[str], typing: bool, timeout_ms: int = 30000) -> None:
        """Send typing notifications for the given rooms."""

        if self._client is None:
            return

        for room_id in room_ids:
            try:
                await self._client.room_typing(
                    room_id,
                    typing_state=typing,
                    timeout=timeout_ms if typing else 0,
                )
                logger.debug(
                    "Sent typing=%s notification for room %s (timeout=%sms)",
                    typing,
                    room_id,
                    timeout_ms,
                )
            except Exception as exc:  # noqa: BLE001 - keep loop alive
                logger.warning("Failed to send typing notification for %s: %s", room_id, exc)

    async def _should_accept_invite(self, room_id: str, invite: InviteInfo) -> bool:
        admin_user = self._settings.admin_user_id
        if admin_user is None:
            logger.debug("Skipping invite to %s; MATRIX_ADMIN_USER_ID not set", room_id)
            return False

        if self._user_id is None:
            logger.debug("Skipping invite to %s; user ID not established", room_id)
            return False

        events = invite.invite_state or []
        for event in events:
            if isinstance(event, InviteMemberEvent):
                if (
                    event.sender == admin_user
                    and event.state_key == self._user_id
                    and event.membership == "invite"
                ):
                    logger.info("Accepting admin invite to %s", room_id)
                    return True
        logger.debug("Invite to %s ignored; no admin invite event found", room_id)
        return False

    async def _accept_invite(self, room_id: str) -> None:
        assert self._client is not None
        try:
            response = await self._client.join(room_id)
        except Exception as exc:  # noqa: BLE001 - keep loop alive
            logger.warning("Failed to join invited room %s: %s", room_id, exc)
            return

        if isinstance(response, JoinError):
            logger.warning("Matrix join error for %s: %s", room_id, response.message)
            return

        self._control_rooms.add(room_id)
        logger.info("Joined control room %s", room_id)

    async def _mark_read(self, room_id: str, event_id: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.room_read_markers(
                room_id,
                fully_read_event=event_id,
                read_event=event_id,
            )
        except Exception as exc:  # noqa: BLE001 - matrix SDK raises broad exceptions
            logger.warning("Failed to update Matrix read marker for %s: %s", room_id, exc)

    async def _create_client(self) -> AsyncClient:
        base_url = self._settings.base_url
        if base_url is None:
            raise RuntimeError("Matrix base URL and access token must be configured")

        homeserver = base_url.rstrip("/")
        client = AsyncClient(homeserver=homeserver)
        token = self._refresh_access_token(force=True)
        client.access_token = token
        client.device_id = client.device_id or "ember-device"

        whoami = await client.whoami()
        if isinstance(whoami, WhoamiError):
            raise RuntimeError(f"Matrix whoami failed: {whoami.message}")
        if not isinstance(whoami, WhoamiResponse) or not whoami.user_id:
            raise RuntimeError("Matrix whoami response missing user_id")

        self._user_id = whoami.user_id
        client.user_id = whoami.user_id
        return client

    def _is_self_message(self, event: RoomMessageText) -> bool:
        return bool(self._user_id and event.sender == self._user_id)

    async def _sync_once(self) -> SyncResponse | None:
        self._refresh_access_token()
        try:
            response = await self._client.sync(timeout=30_000, since=self._since)
        except Exception as exc:  # noqa: BLE001 - propagate diagnostics, keep loop alive
            logger.exception("Matrix sync failed: %s", exc)
            return None

        if isinstance(response, SyncError):
            logger.error("Matrix sync error: %s", response.message)
            return None

        if not isinstance(response, SyncResponse):
            logger.error("Unexpected Matrix sync response: %r", response)
            return None

        return response

    def _refresh_access_token(self, *, force: bool = False) -> str:
        token, changed = self._token_secret.refresh()
        if token is None:
            raise RuntimeError("Matrix access token is not configured")

        if force or changed or self._active_access_token != token:
            self._active_access_token = token
            if self._client is not None:
                self._client.access_token = token
            if changed:
                logger.info("Matrix access token refreshed")
        return token

    def _load_since_token(self) -> str | None:
        try:
            data = self._state_store.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("Failed to read Matrix state store %s: %s", self._state_store, exc)
            return None

        token = data.strip() or None
        if token:
            logger.info("Loaded Matrix sync token from %s", self._state_store)
        return token

    def _persist_since_token(self, token: str) -> None:
        try:
            self._state_store.parent.mkdir(parents=True, exist_ok=True)
            self._state_store.write_text(token, encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to persist Matrix sync token to %s: %s", self._state_store, exc)
