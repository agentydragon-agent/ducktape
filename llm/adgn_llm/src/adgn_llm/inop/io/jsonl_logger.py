"""Reusable JSONL logging utilities."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JSONLLogger:
    """Simple JSONL logger with automatic timestamps."""

    def __init__(self, log_path: Path):
        self.log_path = log_path

    def log(self, **fields: Any) -> None:
        """Log fields as JSON record with timestamp."""
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            **fields,
        }
        with self.log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")


def safe_serialize(obj: Any) -> Any:
    """Safely serialize an object for JSON logging."""
    try:
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if isinstance(obj, dict):
            return obj
        return str(obj)
    except (AttributeError, TypeError):
        return str(obj)
