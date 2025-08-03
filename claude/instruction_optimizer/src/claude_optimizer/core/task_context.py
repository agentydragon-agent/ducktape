"""Simplified task container management using the new task_claude interface."""

from pathlib import Path

from claude_optimizer.core.containerized_claude import TaskClaude, task_claude
from claude_optimizer.database.models import SeedTask


class TaskContainer:
    """Simple wrapper for long-running task containers."""

    def __init__(self, task_id: str, config, db_session):
        self.task_id = task_id
        self.config = config
        self.db_session = db_session
        self._claude: TaskClaude | None = None
        self._working_dir: Path | None = None

    async def start(self, working_dir: Path) -> str:
        """Start container and return container ID for external scripts.

        Args:
            working_dir: Working directory to mount

        Returns:
            str: Container ID
        """
        self._working_dir = working_dir

        # Fetch task prompt and start container context
        session = self.db_session
        task_db = (
            session.query(SeedTask).filter(SeedTask.task_id == self.task_id).first()
        )
        if not task_db:
            raise ValueError(f"Task '{self.task_id}' not found in database")
        prompt = task_db.prompt
        from claude_optimizer.core.logging_utils import DualOutputLogging

        logger = DualOutputLogging.get_logger().bind(task_id=self.task_id)
        self._context_manager = task_claude(
            self.task_id, self.config, working_dir, prompt, logger, self.db_session,
        )
        self._claude = await self._context_manager.__aenter__()

        return self._claude._container.id

    async def stop(self):
        """Stop and clean up the container."""
        if self._claude and hasattr(self, "_context_manager"):
            try:
                await self._context_manager.__aexit__(None, None, None)
            finally:
                self._claude = None
                del self._context_manager

    def get_container_id(self) -> str | None:
        """Get current container ID if running."""
        return (
            self._claude._container.id
            if self._claude and self._claude._container
            else None
        )
