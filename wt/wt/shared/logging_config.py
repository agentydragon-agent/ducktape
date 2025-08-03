import json
import logging
import logging.handlers
from datetime import datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields if present
        if "extra_fields" in record.__dict__:
            log_entry.update(record.__dict__["extra_fields"])

        return json.dumps(log_entry)


class OperationLogger:
    def __init__(self, config, enabled: bool = True):
        self.config = config
        self.enabled = enabled
        self.logger = logging.getLogger("wt.operations")

        if enabled:
            self._setup_logger()

    def _setup_logger(self) -> None:
        # Create rotating file handler
        handler = logging.handlers.RotatingFileHandler(
            self.config.operations_log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )

        # Use JSON formatter
        handler.setFormatter(JSONFormatter())

        # Configure logger
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(handler)

        # Prevent duplicate logs
        self.logger.propagate = False

    def log_operation(self, operation: str, worktree_name: str, **kwargs: Any) -> None:
        if not self.enabled:
            return

        extra_fields = {
            "operation": operation,
            "worktree": worktree_name,
            "details": kwargs,
        }

        self.logger.info(
            f"Operation: {operation} on worktree: {worktree_name}",
            extra={"extra_fields": extra_fields},
        )

    def log_error(
        self,
        operation: str,
        worktree_name: str,
        error: str,
        **kwargs: Any,
    ) -> None:
        if not self.enabled:
            return

        extra_fields = {
            "operation": operation,
            "worktree": worktree_name,
            "error": error,
            "details": kwargs,
        }

        self.logger.error(
            f"Operation failed: {operation} on worktree: {worktree_name} - {error}",
            extra={"extra_fields": extra_fields},
        )


def setup_logging(config, log_level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.wt_dir / "wt.log"),
        ],
    )
