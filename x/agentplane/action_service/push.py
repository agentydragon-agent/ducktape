"""Action approval Web Push delivery.

The Action Service owns delivery because it observes the committed Action event stream. Browser
registration and the service worker remain integration-app concerns; subscriptions are scoped to
the authenticated operator principal and never grant authority by themselves.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import logging

import httpx
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from pydantic import BaseModel, Field, SecretStr
from pywebpush import WebPusher
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from x.agentplane.action_service.db import PushSubscriptionRow
from x.agentplane.action_service.models import ActionRequestView, ActionState

logger = logging.getLogger(__name__)
PUSH_TTL_SECONDS = 600
_DEAD_SUBSCRIPTION_STATUSES = {404, 410}


class WebPushSettings(BaseModel):
    private_key_pem: SecretStr = Field(min_length=1)
    subject: str = Field(min_length=1)
    public_base_url: str = Field(min_length=1)


class PushShow(BaseModel):
    kind: str = "show"
    action_id: str
    action_group: str
    action_name: str
    version: int
    url: str


class PushRetract(BaseModel):
    kind: str = "retract"
    action_id: str
    outcome: str


class PushIdentity:
    def __init__(self, settings: WebPushSettings) -> None:
        self._vapid = Vapid02.from_pem(settings.private_key_pem.get_secret_value().encode())
        self._subject = settings.subject

    @property
    def application_server_key(self) -> str:
        point = self._vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return base64.urlsafe_b64encode(point).rstrip(b"=").decode()

    def authorization(self, endpoint: str) -> str:
        parsed = httpx.URL(endpoint)
        expiry = int(datetime.datetime.now(datetime.UTC).timestamp()) + 3 * 60 * 60
        audience = f"{parsed.scheme}://{parsed.netloc.decode()}"
        return str(self._vapid.sign({"aud": audience, "sub": self._subject, "exp": expiry})["Authorization"])


class PushSubscriptionStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(
        self, *, operator_principal: str, endpoint: str, p256dh: str, auth: str, user_agent: str | None
    ) -> None:
        statement = (
            insert(PushSubscriptionRow)
            .values(
                endpoint=endpoint,
                operator_principal=operator_principal,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
                created_at=datetime.datetime.now(datetime.UTC),
            )
            .on_conflict_do_update(
                index_elements=[PushSubscriptionRow.endpoint],
                set_={
                    "operator_principal": operator_principal,
                    "p256dh": p256dh,
                    "auth": auth,
                    "user_agent": user_agent,
                },
            )
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)

    async def list_for(self, operator_principal: str) -> list[PushSubscriptionRow]:
        async with self._sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(PushSubscriptionRow).where(PushSubscriptionRow.operator_principal == operator_principal)
                    )
                ).all()
            )

    async def list_all(self) -> list[PushSubscriptionRow]:
        async with self._sessions() as session:
            return list((await session.scalars(select(PushSubscriptionRow))).all())

    async def delete(self, *, operator_principal: str, endpoint: str) -> bool:
        async with self._sessions.begin() as session:
            row = await session.get(PushSubscriptionRow, endpoint)
            if row is None or row.operator_principal != operator_principal:
                return False
            await session.delete(row)
            return True

    async def drop_dead(self, endpoint: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(delete(PushSubscriptionRow).where(PushSubscriptionRow.endpoint == endpoint))


class ActionPushNotifier:
    def __init__(self, identity: PushIdentity, subscriptions: PushSubscriptionStore, *, base_url: str) -> None:
        self._identity = identity
        self._subscriptions = subscriptions
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=10)

    async def close(self) -> None:
        await self._http.aclose()

    async def pending(self, view: ActionRequestView) -> None:
        await self._send(
            PushShow(
                action_id=str(view.id),
                action_group=view.action.group,
                action_name=view.action.name,
                version=view.version,
                url=f"{self._base_url}/#/actions/{view.id}",
            )
        )

    async def resolved(self, view: ActionRequestView) -> None:
        outcome = "Approved" if view.state is not ActionState.DENIED else "Denied"
        await self._send(PushRetract(action_id=str(view.id), outcome=outcome))

    async def _send(self, message: PushShow | PushRetract) -> None:
        payload = message.model_dump_json().encode()
        subscriptions = await self._subscriptions.list_all()
        await asyncio.gather(*(self._send_one(row, payload, message.action_id) for row in subscriptions))

    async def _send_one(self, row: PushSubscriptionRow, payload: bytes, action_id: str) -> None:
        try:
            encoded = WebPusher({"endpoint": row.endpoint, "keys": {"p256dh": row.p256dh, "auth": row.auth}}).encode(
                payload
            )
            response = await self._http.post(
                row.endpoint,
                content=encoded["body"],
                headers={
                    "Authorization": self._identity.authorization(row.endpoint),
                    "Content-Encoding": "aes128gcm",
                    "Content-Type": "application/octet-stream",
                    "TTL": str(PUSH_TTL_SECONDS),
                    "Urgency": "high",
                    "Topic": action_id[:32],
                },
            )
            if response.status_code in _DEAD_SUBSCRIPTION_STATUSES:
                await self._subscriptions.drop_dead(row.endpoint)
            elif response.is_error:
                logger.warning("web push rejected by %s: %s", row.endpoint.split("/", 3)[0], response.status_code)
        except Exception:
            logger.warning("web push send failed; endpoint and error details withheld")
