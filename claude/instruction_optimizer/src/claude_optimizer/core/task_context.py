"""Simplified task container management using the new task_claude interface."""

from pathlib import Path
from typing import Optional

from claude_optimizer.core.containerized_claude import TaskClaude, task_claude


class TaskContainer:
    """Simple wrapper for long-running task containers."""
    
    def __init__(self, task_id: str, config):
        self.task_id = task_id
        self.config = config
        self._claude: Optional[TaskClaude] = None
        self._working_dir: Optional[Path] = None
        
    async def start(self, working_dir: Path) -> str:
        """Start container and return container ID for external scripts.
        
        Args:
            working_dir: Working directory to mount
            
        Returns:
            str: Container ID
        """
        self._working_dir = working_dir
        
        # Use the context manager but keep it alive
        self._context_manager = task_claude(self.task_id, self.config, working_dir)
        self._claude = await self._context_manager.__aenter__()
        
        return self._claude._container.id
    
    async def stop(self):
        """Stop and clean up the container."""
        if self._claude and hasattr(self, '_context_manager'):
            try:
                await self._context_manager.__aexit__(None, None, None)
            finally:
                self._claude = None
                del self._context_manager
    
    def get_container_id(self) -> Optional[str]:
        """Get current container ID if running."""
        return self._claude._container.id if self._claude and self._claude._container else None