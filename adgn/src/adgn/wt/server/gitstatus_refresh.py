import asyncio
import logging
from pathlib import Path
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


class DebouncedGitstatusRefresh:
    def __init__(
        self,
        worktree_path: Path,
        refresh_callback,
        debounce_delay: float = 0.5,
    ):
        self.worktree_path = worktree_path
        self.refresh_callback = refresh_callback
        self.debounce_delay = debounce_delay
        self._pending: asyncio.Task | None = None

        self.observer: Observer | None = None
        self.handler = _GitHandler(self)
        self.is_running = False

    def _resolve_git_dir(self) -> Path | None:
        git_path = self.worktree_path / ".git"
        if git_path.is_dir():
            return git_path
        if git_path.is_file():
            try:
                content = git_path.read_text(encoding="utf-8", errors="ignore").strip()
                if content.startswith("gitdir:"):
                    raw = content.split(":", 1)[1].strip()
                    p = Path(raw)
                    return p if p.is_absolute() else (self.worktree_path / p).resolve()
            except OSError:
                # Linked .git files use 'gitdir: <path>' format per git docs; it's safe to skip on read errors
                return None
        return None

    async def start(self):
        if self.is_running:
            return
        self.is_running = True
        git_dir = self._resolve_git_dir()
        self.observer = Observer()
        if git_dir and git_dir.exists():
            self.observer.schedule(self.handler, str(git_dir), recursive=True)
            self.observer.start()
            logger.debug("Watching git dir for status refresh: %s", git_dir)
        else:
            logger.debug("No git dir found for %s", self.worktree_path)

    async def stop(self):
        self.is_running = False
        if self.observer:
            try:
                self.observer.stop()
                # Join the watchdog thread without blocking the event loop (Python 3.12)
                await asyncio.to_thread(self.observer.join)
            finally:
                self.observer = None
        if self._pending:
            self._pending.cancel()
            self._pending = None

    def trigger(self, reason: str):
        if self._pending:
            self._pending.cancel()
        try:
            loop = asyncio.get_running_loop()
            self._pending = loop.create_task(self._debounced(reason))
        except RuntimeError:
            # No running loop (watchdog thread); schedule soon on default loop
            def _enqueue():
                try:
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self._debounced(reason)),
                    )
                except Exception:
                    logger.exception("Failed to enqueue debounced gitstatus refresh")

            threading.Thread(target=_enqueue, daemon=True).start()

    async def _debounced(self, reason: str):
        try:
            await asyncio.sleep(self.debounce_delay)
            await self.refresh_callback(reason)
        except asyncio.CancelledError:
            pass


class _GitHandler(FileSystemEventHandler):
    def __init__(self, parent: DebouncedGitstatusRefresh):
        self.parent = parent

    def on_modified(self, event):
        if not event.is_directory:
            self.parent.trigger("modified")

    def on_created(self, event):
        if not event.is_directory:
            self.parent.trigger("created")
