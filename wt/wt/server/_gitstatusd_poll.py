import asyncio
import contextlib
import logging

logger = logging.getLogger(__name__)


class PollMixin:
    _poll_task: asyncio.Task | None = None

    async def start_polling(self):
        if not self._poll_task:
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_polling(self):
        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None

    async def _poll_loop(self) -> None:
        try:
            while True:
                try:
                    await self.update_working_status()
                except Exception:
                    logger.debug("poll update failed", exc_info=True)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
