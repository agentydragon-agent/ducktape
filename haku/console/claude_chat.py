"""Operator chat sessions backed by Claude Code in Agent Sandbox pods."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, TextBlock
from claude_agent_sdk.types import StreamEvent
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from kubernetes_asyncio import client as k8s_client, config as k8s_config
from kubernetes_asyncio.client import ApiClient, CustomObjectsApi
from kubernetes_asyncio.config.config_exception import ConfigException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from haku.console.config import ClaudeRuntimeConfig
from haku.console.database_schema import ClaudeChatMessage, ClaudeChatSession
from haku.console.operator_auth import OperatorActorDep
from haku.runtime.agent_sdk_transport.options import build_claude_launch, enable_fine_grained_streaming
from haku.runtime.agent_sdk_transport.protocol import TextWebSocket
from haku.runtime.agent_sdk_transport.transport import WebSocketTransport

router = APIRouter(tags=["claude-chat"])
internal_router = APIRouter(tags=["claude-chat-internal"])

SessionStatus = Literal["provisioning", "ready", "responding", "closing", "closed", "failed"]
MessageRole = Literal["user", "assistant"]
MessageStatus = Literal["pending", "streaming", "complete", "failed"]


class ClaudeChatMessageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    role: MessageRole
    status: MessageStatus
    content: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class ClaudeChatSessionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    status: SessionStatus
    error: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[ClaudeChatMessageView]


class ClaudeChatPrompt(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class SandboxClaims(Protocol):
    async def create(self, *, session_id: UUID, bridge_token: str, expires_at: datetime) -> None: ...

    async def delete(self, *, session_id: UUID) -> None: ...

    async def aclose(self) -> None: ...


class KubernetesSandboxClaims:
    """Create the narrow declarative SandboxClaim used by one chat session."""

    def __init__(self, config: ClaudeRuntimeConfig):
        self._config = config
        self._api_client: ApiClient | None = None
        self._custom_objects: CustomObjectsApi | None = None
        self._lock = asyncio.Lock()

    async def _client(self) -> CustomObjectsApi:
        if self._custom_objects is not None:
            return self._custom_objects
        async with self._lock:
            if self._custom_objects is None:
                configuration = k8s_client.Configuration()
                try:
                    k8s_config.load_incluster_config(client_configuration=configuration)
                except ConfigException as error:
                    raise RuntimeError("Kubernetes in-cluster configuration is unavailable") from error
                self._api_client = ApiClient(configuration=configuration)
                self._custom_objects = CustomObjectsApi(self._api_client)
        return self._custom_objects

    def _claim_name(self, session_id: UUID) -> str:
        return f"claude-{session_id.hex}"

    async def create(self, *, session_id: UUID, bridge_token: str, expires_at: datetime) -> None:
        body = {
            "apiVersion": "extensions.agents.x-k8s.io/v1beta1",
            "kind": "SandboxClaim",
            "metadata": {
                "name": self._claim_name(session_id),
                "labels": {
                    "app.kubernetes.io/managed-by": "haku-console",
                    "haku.allegedly.works/runtime": "claude-chat",
                },
            },
            "spec": {
                "warmPoolRef": {"name": self._config.warm_pool},
                "lifecycle": {
                    "shutdownPolicy": "DeleteForeground",
                    "shutdownTime": expires_at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                },
                "env": [
                    {"name": "HAKU_CLAUDE_SESSION_ID", "value": str(session_id)},
                    {"name": "HAKU_AGENT_SDK_RUNNER_TOKEN", "value": bridge_token},
                ],
            },
        }
        client = await self._client()
        await client.create_namespaced_custom_object(
            "extensions.agents.x-k8s.io", "v1beta1", self._config.namespace, "sandboxclaims", body
        )

    async def delete(self, *, session_id: UUID) -> None:
        client = await self._client()
        try:
            await client.delete_namespaced_custom_object(
                "extensions.agents.x-k8s.io",
                "v1beta1",
                self._config.namespace,
                "sandboxclaims",
                self._claim_name(session_id),
                body=k8s_client.V1DeleteOptions(propagation_policy="Foreground"),
            )
        except k8s_client.ApiException as error:
            if error.status != 404:
                raise

    async def aclose(self) -> None:
        if self._api_client is not None:
            await self._api_client.close()
            self._api_client = None
            self._custom_objects = None


class ClaudeChatStore:
    """Small synchronous Postgres store; async callers dispatch operations to worker threads."""

    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    @staticmethod
    def _fingerprint(token: str) -> bytes:
        return hashlib.sha256(token.encode()).digest()

    def create(self, operator_id: UUID) -> tuple[ClaudeChatSessionView, str]:
        now = datetime.now(UTC)
        session_id = uuid4()
        bridge_token = secrets.token_urlsafe(32)
        with self._sessions.begin() as db:
            db.add(
                ClaudeChatSession(
                    session_id=session_id,
                    operator_id=operator_id,
                    status="provisioning",
                    bridge_token_fingerprint=self._fingerprint(bridge_token),
                    bridge_connected_at=None,
                    error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get(operator_id, session_id), bridge_token

    def get(self, operator_id: UUID, session_id: UUID) -> ClaudeChatSessionView:
        with self._sessions() as db:
            record = db.scalar(
                select(ClaudeChatSession).where(
                    ClaudeChatSession.session_id == session_id, ClaudeChatSession.operator_id == operator_id
                )
            )
            if record is None:
                raise KeyError(session_id)
            messages = list(
                db.scalars(
                    select(ClaudeChatMessage)
                    .where(ClaudeChatMessage.session_id == session_id)
                    .order_by(ClaudeChatMessage.created_at, ClaudeChatMessage.message_id)
                )
            )
            return _session_view(record, messages)

    def authenticate_bridge(self, session_id: UUID, token: str) -> bool:
        now = datetime.now(UTC)
        with self._sessions.begin() as db:
            record = db.get(ClaudeChatSession, session_id, with_for_update=True)
            if (
                record is None
                or record.status != "provisioning"
                or record.bridge_connected_at is not None
                or not secrets.compare_digest(record.bridge_token_fingerprint, self._fingerprint(token))
            ):
                return False
            record.bridge_connected_at = now
            record.bridge_token_fingerprint = b""
            record.status = "ready"
            record.updated_at = now
            return True

    def enqueue_prompt(self, operator_id: UUID, session_id: UUID, text: str) -> ClaudeChatMessageView:
        now = datetime.now(UTC)
        with self._sessions.begin() as db:
            chat = db.scalar(
                select(ClaudeChatSession)
                .where(ClaudeChatSession.session_id == session_id, ClaudeChatSession.operator_id == operator_id)
                .with_for_update()
            )
            if chat is None:
                raise KeyError(session_id)
            if chat.status != "ready":
                raise RuntimeError(f"session is not ready (status={chat.status})")
            existing = db.scalar(
                select(ClaudeChatMessage).where(
                    ClaudeChatMessage.session_id == session_id, ClaudeChatMessage.status == "pending"
                )
            )
            if existing is not None:
                raise RuntimeError("a prompt is already queued")
            message = ClaudeChatMessage(
                message_id=uuid4(),
                session_id=session_id,
                role="user",
                status="pending",
                content=text,
                error=None,
                created_at=now,
                updated_at=now,
            )
            db.add(message)
            chat.status = "responding"
            chat.updated_at = now
        return _message_view(message)

    def next_prompt(self, session_id: UUID) -> tuple[UUID, str] | None:
        with self._sessions.begin() as db:
            chat = db.get(ClaudeChatSession, session_id, with_for_update=True)
            if chat is None or chat.status in {"closing", "closed", "failed"}:
                return None
            message = db.scalar(
                select(ClaudeChatMessage)
                .where(
                    ClaudeChatMessage.session_id == session_id,
                    ClaudeChatMessage.role == "user",
                    ClaudeChatMessage.status == "pending",
                )
                .order_by(ClaudeChatMessage.created_at)
                .with_for_update(skip_locked=True)
            )
            if message is None:
                return None
            now = datetime.now(UTC)
            message.status = "complete"
            message.updated_at = now
            chat.status = "responding"
            chat.updated_at = now
            return message.message_id, message.content

    def begin_assistant(self, session_id: UUID) -> UUID:
        now = datetime.now(UTC)
        message_id = uuid4()
        with self._sessions.begin() as db:
            db.add(
                ClaudeChatMessage(
                    message_id=message_id,
                    session_id=session_id,
                    role="assistant",
                    status="streaming",
                    content="",
                    error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return message_id

    def update_assistant(self, session_id: UUID, message_id: UUID, content: str, *, complete: bool = False) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as db:
            message = db.get(ClaudeChatMessage, message_id)
            chat = db.get(ClaudeChatSession, session_id)
            if message is None or chat is None:
                return
            message.content = content
            message.status = "complete" if complete else "streaming"
            message.updated_at = now
            chat.status = "ready" if complete else "responding"
            chat.updated_at = now

    def fail(self, session_id: UUID, error: str, message_id: UUID | None = None) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as db:
            chat = db.get(ClaudeChatSession, session_id)
            if chat is not None:
                chat.status = "failed"
                chat.error = error
                chat.updated_at = now
            if message_id is not None:
                message = db.get(ClaudeChatMessage, message_id)
                if message is not None:
                    message.status = "failed"
                    message.error = error
                    message.updated_at = now

    def request_close(self, operator_id: UUID, session_id: UUID) -> None:
        with self._sessions.begin() as db:
            chat = db.scalar(
                select(ClaudeChatSession)
                .where(ClaudeChatSession.session_id == session_id, ClaudeChatSession.operator_id == operator_id)
                .with_for_update()
            )
            if chat is None:
                raise KeyError(session_id)
            chat.status = "closing"
            chat.updated_at = datetime.now(UTC)

    def status(self, session_id: UUID) -> str | None:
        with self._sessions() as db:
            chat = db.get(ClaudeChatSession, session_id)
            return chat.status if chat is not None else None

    def closed(self, session_id: UUID) -> None:
        with self._sessions.begin() as db:
            chat = db.get(ClaudeChatSession, session_id)
            if chat is not None and chat.status != "failed":
                chat.status = "closed"
                chat.updated_at = datetime.now(UTC)


class StarletteTextWebSocket(TextWebSocket):
    def __init__(self, websocket: WebSocket):
        self._websocket = websocket

    async def send_text(self, data: str) -> None:
        await self._websocket.send_text(data)

    async def receive_text(self) -> str:
        return await self._websocket.receive_text()

    async def close(self) -> None:
        await self._websocket.close()


class ClaudeChatService:
    def __init__(self, config: ClaudeRuntimeConfig, store: ClaudeChatStore, claims: SandboxClaims):
        self._config = config
        self._store = store
        self._claims = claims

    async def create(self, operator_id: UUID) -> ClaudeChatSessionView:
        view, token = await asyncio.to_thread(self._store.create, operator_id)
        try:
            await self._claims.create(
                session_id=view.session_id,
                bridge_token=token,
                expires_at=datetime.now(UTC) + timedelta(seconds=self._config.session_ttl_seconds),
            )
        except Exception as error:
            await asyncio.to_thread(self._store.fail, view.session_id, f"sandbox provisioning failed: {error}")
            raise
        return view

    async def dispose(self, operator_id: UUID, session_id: UUID) -> None:
        await asyncio.to_thread(self._store.request_close, operator_id, session_id)
        await self._claims.delete(session_id=session_id)

    async def handle_runner(self, websocket: WebSocket, session_id: UUID, bearer: str) -> None:
        if not await asyncio.to_thread(self._store.authenticate_bridge, session_id, bearer):
            await websocket.close(code=1008, reason="invalid or consumed runner credential")
            return
        await websocket.accept()
        adapter = StarletteTextWebSocket(websocket)
        options = enable_fine_grained_streaming(
            ClaudeAgentOptions(
                cwd=self._config.cwd,
                env=self._config.claude_environment(),
                permission_mode="bypassPermissions",
                setting_sources=[],
            )
        )
        client = ClaudeSDKClient(options=options, transport=WebSocketTransport(adapter, build_claude_launch(options)))
        try:
            await client.connect()
            while True:
                status = await asyncio.to_thread(self._store.status, session_id)
                if status in {None, "closing", "closed", "failed"}:
                    break
                prompt = await asyncio.to_thread(self._store.next_prompt, session_id)
                if prompt is None:
                    await asyncio.sleep(self._config.prompt_poll_seconds)
                    continue
                _, text = prompt
                assistant_id = await asyncio.to_thread(self._store.begin_assistant, session_id)
                try:
                    await self._run_turn(client, session_id, assistant_id, text)
                except Exception as error:
                    await asyncio.to_thread(self._store.fail, session_id, str(error), assistant_id)
                    break
        except WebSocketDisconnect:
            await asyncio.to_thread(self._store.fail, session_id, "sandbox runner disconnected")
        except Exception as error:
            await asyncio.to_thread(self._store.fail, session_id, f"Claude runtime failed: {error}")
        finally:
            await client.disconnect()
            await self._claims.delete(session_id=session_id)
            await asyncio.to_thread(self._store.closed, session_id)

    async def _run_turn(self, client: ClaudeSDKClient, session_id: UUID, assistant_id: UUID, prompt: str) -> None:
        await client.query(prompt)
        streamed = ""
        final_parts: list[str] = []
        result: ResultMessage | None = None
        async for message in client.receive_response():
            if isinstance(message, StreamEvent):
                delta = _text_delta(message.event)
                if delta:
                    streamed += delta
                    await asyncio.to_thread(self._store.update_assistant, session_id, assistant_id, streamed)
            elif isinstance(message, AssistantMessage):
                final_parts.extend(block.text for block in message.content if isinstance(block, TextBlock))
            elif isinstance(message, ResultMessage):
                result = message
        if result is None:
            raise RuntimeError("Claude response ended without a result")
        if result.is_error:
            raise RuntimeError(f"Claude returned {result.subtype}: {result.stop_reason or 'unknown error'}")
        final = "".join(final_parts).strip() or streamed.strip() or (result.result or "").strip()
        await asyncio.to_thread(self._store.update_assistant, session_id, assistant_id, final, complete=True)

    async def aclose(self) -> None:
        await self._claims.aclose()


def _text_delta(event: dict[str, Any]) -> str:
    if event.get("type") != "content_block_delta":
        return ""
    delta = event.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return ""
    text = delta.get("text")
    return text if isinstance(text, str) else ""


def _message_view(message: ClaudeChatMessage) -> ClaudeChatMessageView:
    return ClaudeChatMessageView(
        message_id=message.message_id,
        role=cast(MessageRole, message.role),
        status=cast(MessageStatus, message.status),
        content=message.content,
        error=message.error,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def _session_view(record: ClaudeChatSession, messages: list[ClaudeChatMessage]) -> ClaudeChatSessionView:
    return ClaudeChatSessionView(
        session_id=record.session_id,
        status=cast(SessionStatus, record.status),
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        messages=[_message_view(message) for message in messages],
    )


def _service(request: Request) -> ClaudeChatService:
    service = cast(ClaudeChatService | None, request.app.state.claude_chat_service)
    if service is None:
        raise HTTPException(status_code=503, detail="sandbox Claude chat is not configured")
    return service


def _store(request: Request) -> ClaudeChatStore:
    store = cast(ClaudeChatStore | None, request.app.state.claude_chat_store)
    if store is None:
        raise HTTPException(status_code=503, detail="sandbox Claude chat is not configured")
    return store


ClaudeChatServiceDep = Annotated[ClaudeChatService, Depends(_service)]
ClaudeChatStoreDep = Annotated[ClaudeChatStore, Depends(_store)]


@router.post("/api/claude/sessions")
async def create_session(actor: OperatorActorDep, service: ClaudeChatServiceDep) -> ClaudeChatSessionView:
    try:
        return await service.create(actor.operator_id)
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/api/claude/sessions/{session_id}")
async def get_session(session_id: UUID, actor: OperatorActorDep, store: ClaudeChatStoreDep) -> ClaudeChatSessionView:
    try:
        return await asyncio.to_thread(store.get, actor.operator_id, session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Claude chat session not found") from error


@router.post("/api/claude/sessions/{session_id}/messages")
async def send_message(
    session_id: UUID, body: ClaudeChatPrompt, actor: OperatorActorDep, store: ClaudeChatStoreDep
) -> ClaudeChatMessageView:
    try:
        return await asyncio.to_thread(store.enqueue_prompt, actor.operator_id, session_id, body.text)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Claude chat session not found") from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/api/claude/sessions/{session_id}", status_code=204)
async def delete_session(session_id: UUID, actor: OperatorActorDep, service: ClaudeChatServiceDep) -> None:
    try:
        await service.dispose(actor.operator_id, session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Claude chat session not found") from error


@internal_router.websocket("/internal/claude/runner/{session_id}")
async def runner_websocket(websocket: WebSocket, session_id: UUID) -> None:
    service = cast(ClaudeChatService | None, websocket.app.state.claude_chat_service)
    authorization = websocket.headers.get("authorization", "")
    scheme, _, bearer = authorization.partition(" ")
    if service is None or scheme.lower() != "bearer" or not bearer:
        await websocket.close(code=1008, reason="runner authentication required")
        return
    await service.handle_runner(websocket, session_id, bearer)
