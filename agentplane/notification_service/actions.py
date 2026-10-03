"""The only V1 provider: canonical Action events, through a read-only delegated API."""

import asyncio
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import TypeAdapter

from agentplane.action_service.models import ActionEventView
from agentplane.subjects import ServiceAccountRef

_EVENTS = TypeAdapter(list[ActionEventView])


class Actions:
    def __init__(self, http: httpx.AsyncClient, token_file: Path) -> None:
        self.http = http
        self.token_file = token_file

    async def events(self, owner: ServiceAccountRef, request_id: UUID, after_sequence: int) -> list[ActionEventView]:
        token = (await asyncio.to_thread(self.token_file.read_text)).strip()
        response = await self.http.get(
            f"/v1/service/action-requests/{request_id}/events",
            params={"owner_namespace": owner.namespace, "owner_name": owner.name, "after_sequence": after_sequence},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return _EVENTS.validate_json(response.content)
