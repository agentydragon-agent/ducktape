"""Custom exceptions for the Claude optimizer."""


class ContextWindowExceededError(Exception):
    """Raised when input exceeds the model's context window."""

    def __init__(self, message: str, task_id: str | None = None, agent_id: int | None = None):
        super().__init__(message)
        self.task_id = task_id
        self.agent_id = agent_id
