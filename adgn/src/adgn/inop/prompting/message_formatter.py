"""Message formatting utilities for structured logging."""

from typing import Any, Protocol

from claude_code_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)


class StructuredLogger(Protocol):
    """Protocol for structured logging (e.g., structlog)."""

    def info(self, event: str, **kwargs: Any) -> None:
        """Log an info-level message with structured fields."""
        ...

    def bind(self, **kwargs: Any) -> "StructuredLogger":
        """Bind additional context to logger."""
        ...


class MessageFormatter:
    """Utilities for formatting message content for logging."""

    DEFAULT_TRUNCATE = 100
    ARG_TRUNCATE = 30
    CONTENT_TRUNCATE = 60

    @staticmethod
    def truncate(text: str, limit: int) -> str:
        """Truncate text to specified limit with ellipsis."""
        return text[:limit] + "..." if len(text) > limit else text

    @staticmethod
    def clean_text(text: str) -> str:
        """Remove newlines for cleaner log output."""
        return text.replace("\n", " ")

    @classmethod
    def format_preview(cls, content: str, limit: int = DEFAULT_TRUNCATE) -> str:
        """Clean and truncate text for preview."""
        return cls.clean_text(cls.truncate(content, limit))

    @staticmethod
    def safe_str(content: Any) -> str:
        """Safely convert any content to string."""
        return content if isinstance(content, str) else str(content)


def log_system_message(logger: StructuredLogger, message: SystemMessage) -> None:
    """Log system message details.

    Args:
        logger: Structured logger (e.g., structlog) with info() and bind() methods.
        message: System message to log.
    """
    logger.info("System message", subtype=message.subtype)


def log_assistant_message(logger: StructuredLogger, message: AssistantMessage) -> None:
    """Log assistant message with tool usage details."""
    tool_uses_full = []  # Complete data for JSON logs
    text_content = ""

    for block in message.content:
        if isinstance(block, TextBlock):
            text_content = block.text
        elif isinstance(block, ToolUseBlock):
            # Store complete tool usage data (no truncation for structured logs)
            tool_uses_full.append({"name": block.name, "args": dict(block.input)})
        elif isinstance(block, ToolResultBlock):
            content_str = MessageFormatter.safe_str(block.content)
            logger.info(
                "Tool result",
                tool_use_id=block.tool_use_id[:8],
                content_preview=MessageFormatter.format_preview(content_str, MessageFormatter.CONTENT_TRUNCATE),
            )

    if tool_uses_full:
        logger.info("Tool usage", tools=tool_uses_full)
    elif text_content:
        logger.info("Assistant message", content_preview=MessageFormatter.format_preview(text_content))


def log_user_message(logger: StructuredLogger, message: UserMessage) -> None:
    """Log user message, handling both string and list content."""
    # Handle list content (e.g., tool results)
    if isinstance(message.content, list) and message.content:
        first_item = message.content[0]
        if isinstance(first_item, dict) and first_item.get("type") == "tool_result":
            tool_id = first_item.get("tool_use_id", "unknown")[:8]
            content = MessageFormatter.safe_str(first_item.get("content", ""))
            logger.info(
                "Tool result",
                tool_use_id=tool_id,
                content_preview=MessageFormatter.format_preview(content, MessageFormatter.CONTENT_TRUNCATE),
            )
            return

    # Handle string content or fallback
    content_str = MessageFormatter.safe_str(message.content)
    if content_str and content_str != "[]":  # Don't log empty lists
        logger.info("User message", content_preview=MessageFormatter.format_preview(content_str))
    else:
        logger.info("User message", content="empty")


def log_result_message(logger: StructuredLogger, message: ResultMessage) -> None:
    """Log result message with execution details."""
    logger.info(
        "Result message", duration_ms=message.duration_ms, cost_usd=message.total_cost_usd, is_error=message.is_error
    )


def log_message_summary(
    message: SystemMessage | AssistantMessage | UserMessage | ResultMessage,
    logger: StructuredLogger,
    agent_id: int | None = None,
) -> None:
    """Log a structured summary of a coding agent SDK message."""
    message_logger = logger.bind(agent_id=agent_id, message_type=type(message).__name__)

    if isinstance(message, SystemMessage):
        log_system_message(message_logger, message)
    elif isinstance(message, AssistantMessage):
        log_assistant_message(message_logger, message)
    elif isinstance(message, UserMessage):
        log_user_message(message_logger, message)
    elif isinstance(message, ResultMessage):
        log_result_message(message_logger, message)
    else:
        message_logger.info("Unknown message type")


class MessageLogger:
    """Adapter providing structured message logging using MessageFormatter utilities."""

    def __init__(self, logger: StructuredLogger):
        """Initialize MessageLogger with a structured logger.

        Args:
            logger: Structured logger (e.g., structlog) with info() and bind() methods.
        """
        self.logger = logger

    def log_system(self, message: SystemMessage) -> None:
        log_system_message(self.logger, message)

    def log_assistant(self, message: AssistantMessage) -> None:
        log_assistant_message(self.logger, message)

    def log_user(self, message: UserMessage) -> None:
        log_user_message(self.logger, message)

    def log_result(self, message: ResultMessage) -> None:
        log_result_message(self.logger, message)

    def log_summary(
        self, message: SystemMessage | AssistantMessage | UserMessage | ResultMessage, agent_id: int
    ) -> None:
        log_message_summary(message, self.logger, agent_id)
