from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
import time

from nio import AsyncClient, AsyncClientConfig, RoomMessageText
from nio.responses import (
    JoinError,
    RoomCreateError,
    RoomCreateResponse,
    RoomSendError,
    SyncError,
    WhoamiError,
    WhoamiResponse,
)
from pydantic import BaseModel, Field

from .common import CommandError


class MatrixMessage(BaseModel):
    direction: str
    sender: str
    body: str
    event_id: str | None = None
    timestamp: int | None = None
    room_id: str | None = None


class MatrixTranscript(BaseModel):
    events: list[MatrixMessage] = Field(default_factory=list)


def render_matrix_transcript(transcript: MatrixTranscript) -> str:
    lines = []
    for event in sorted(transcript.events, key=lambda e: e.timestamp or 0):
        if event.timestamp:
            ts = datetime.fromtimestamp(
                event.timestamp / 1000, tz=timezone.utc
            ).isoformat()
        else:
            ts = ""
        direction = "user" if event.direction == "in" else "ember"
        lines.append(f"{ts} {event.sender} ({direction}): {event.body}")
    return "\n".join(lines)


@dataclass(frozen=True)
class MatrixConnection:
    base_url: str
    access_token: str


class MatrixHarness:
    def __init__(
        self,
        connection: MatrixConnection,
        ember_user_id: str,
        run_id: str,
        artifact_dir: Path,
        room_id: str | None = None,
    ) -> None:
        self._base_url = connection.base_url
        self._access_token = connection.access_token
        self._ember_user_id = ember_user_id
        self._room_id = room_id
        self._run_id = run_id
        self._artifact_dir = artifact_dir
        self._client: AsyncClient | None = None
        self._user_id: str | None = None
        self._store_dir: Path | None = None
        self._transcript: list[MatrixMessage] = []

    @property
    def room_id(self) -> str:
        if self._room_id is None:
            raise RuntimeError("Matrix room not initialised")
        return self._room_id

    @property
    def ember_user_id(self) -> str:
        return self._ember_user_id

    @property
    def transcript(self) -> list[MatrixMessage]:
        return list(self._transcript)

    async def __aenter__(self) -> MatrixHarness:
        config = AsyncClientConfig(encryption_enabled=False, store_sync_tokens=False)
        self._store_dir = Path(tempfile.mkdtemp(prefix=f"matrix-store-{self._run_id}-"))
        self._client = AsyncClient(
            homeserver=self._base_url,
            user=None,
            config=config,
            store_path=str(self._store_dir),
        )
        self._client.access_token = self._access_token
        whoami = await self._client.whoami()
        if isinstance(whoami, WhoamiResponse):
            self._user_id = whoami.user_id
            self._client.user_id = whoami.user_id
        elif isinstance(whoami, WhoamiError):
            raise CommandError(f"Matrix whoami failed: {whoami.message}")
        else:
            raise CommandError("Unexpected Matrix whoami response")

        if self._room_id:
            join_resp = await self._client.join(self._room_id)
            if isinstance(join_resp, JoinError) and "already in the room" not in (
                join_resp.message or ""
            ):
                raise CommandError(f"Matrix join failed: {join_resp.message}")
        else:
            create_resp = await self._client.room_create(
                is_direct=True,
                invite=[self._ember_user_id],
                name=f"ember-eval-{self._run_id}",
                preset="trusted_private_chat",
            )
            if isinstance(create_resp, RoomCreateError):
                raise CommandError(f"Matrix room create failed: {create_resp.message}")
            if not isinstance(create_resp, RoomCreateResponse):
                raise CommandError("Unexpected Matrix room create response")
            self._room_id = create_resp.room_id

        sync_resp = await self._client.sync(timeout=3_000)
        if isinstance(sync_resp, SyncError):
            raise CommandError(f"Matrix initial sync failed: {sync_resp.message}")
        self._record_events(sync_resp)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
        if self._store_dir is not None:
            shutil.rmtree(self._store_dir, ignore_errors=True)
            self._store_dir = None

    async def send_message(self, text: str) -> None:
        client = self._require_client()
        response = await client.room_send(
            self.room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": text},
        )
        if isinstance(response, RoomSendError):
            raise CommandError(f"Matrix send failed: {response.message}")
        self._transcript.append(
            MatrixMessage(
                direction="out",
                sender=self._user_id or "",
                body=text,
                event_id=response.event_id,
                room_id=self.room_id,
            )
        )

    async def wait_for_message(
        self,
        *,
        sender: str | None = None,
        timeout_seconds: int = 60,
    ) -> MatrixMessage:
        client = self._require_client()
        deadline = time.monotonic() + max(timeout_seconds, 1)
        sender = sender or self._ember_user_id
        while time.monotonic() < deadline:
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            sync_resp = await client.sync(timeout=remaining)
            if isinstance(sync_resp, SyncError):
                raise CommandError(f"Matrix sync error: {sync_resp.message}")
            events = self._record_events(sync_resp)
            for event in events:
                if event.sender == sender:
                    return event
            await asyncio.sleep(1)
        raise TimeoutError(f"No Matrix message from {sender} within {timeout_seconds}s")

    async def expect_reply(
        self, expected: str, timeout_seconds: int = 60
    ) -> MatrixMessage:
        message = await self.wait_for_message(timeout_seconds=timeout_seconds)
        if message.body.strip() != expected.strip():
            raise AssertionError(
                f"Expected reply '{expected}' but received '{message.body.strip()}'"
            )
        return message

    def _require_client(self) -> AsyncClient:
        if self._client is None:
            raise RuntimeError("Matrix client not initialised")
        return self._client

    def _record_events(self, response) -> list[MatrixMessage]:
        recorded: list[MatrixMessage] = []
        if not response or not response.rooms or not response.rooms.join:
            return recorded
        room = response.rooms.join.get(self._room_id or "")
        if not room or not room.timeline or not room.timeline.events:
            return recorded
        for event in room.timeline.events:
            if not isinstance(event, RoomMessageText):
                continue
            message = MatrixMessage(
                direction="out" if event.sender == (self._user_id or "") else "in",
                sender=event.sender or "",
                body=event.body if isinstance(event.body, str) else str(event.body),
                event_id=event.event_id,
                timestamp=event.server_timestamp,
                room_id=self._room_id,
            )
            self._transcript.append(message)
            recorded.append(message)
        return recorded
