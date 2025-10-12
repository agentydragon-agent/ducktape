from __future__ import annotations

import asyncio
import logging

from nio import RoomMessageText
from openai import AsyncOpenAI

from .config import PilotSettings
from .history import ConversationHistory
from .matrix_client import MatrixClient
from .openai_agent import OpenAIAgent

logger = logging.getLogger(__name__)


class PilotRuntime:
    def __init__(self, settings: PilotSettings) -> None:
        self._settings = settings
        self._history = ConversationHistory(settings.history_path)
        self._matrix_client = MatrixClient(settings.matrix)
        self._openai_client = AsyncOpenAI(api_key=settings.openai.api_key)
        self._agent = OpenAIAgent(settings.openai, self._history, self._openai_client)
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        logger.info("Starting pilot runtime")
        await self._matrix_client.start()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="pilot-runtime-loop")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._matrix_client.close()
        await self._openai_client.close()
        logger.info("Pilot runtime stopped")

    async def restart(self) -> None:
        await self.stop()
        self._history = ConversationHistory(self._settings.history_path)
        self._matrix_client = MatrixClient(self._settings.matrix)
        self._openai_client = AsyncOpenAI(api_key=self._settings.openai.api_key)
        self._agent = OpenAIAgent(self._settings.openai, self._history, self._openai_client)
        await self.start()

    async def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                if not (events := await self._matrix_client.get_events(timeout=60.0)):
                    continue
                message_text = _format_events(events)
                logger.info("Received Matrix batch:\n%s", message_text)
                await self._agent.handle_user_message(message_text)
        except asyncio.CancelledError:
            raise


def _format_events(events: list[RoomMessageText]) -> str:
    lines = []
    for event in events:
        lines.append(f"{event.sender}: {event.body}")
    return "\n".join(lines)
