from __future__ import annotations

import logging
from logging.config import dictConfig
import os
from pathlib import Path

import structlog
from structlog.typing import Processor


def configure_logging() -> None:
    """Single source of truth for logging configuration.

    - Routes ALL logs through stdlib logging (structlog uses stdlib LoggerFactory)
    - Console handler at WARNING+ by default (quiet CLI)
    - Optional file sink at INFO when ADGN_LOG_DIR is set
    - No prints; no library-specific handlers
    """
    log_dir_env = os.getenv("ADGN_LOG_DIR")
    file_enabled = bool(log_dir_env)
    file_path = str((Path(log_dir_env or "./logs") / "adgn.log").resolve()) if file_enabled else None

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "formatters": {
                "console": {"format": "%(levelname)s %(name)s: %(message)s"},
                "file": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "WARNING",
                    "formatter": "console",
                    "stream": "ext://sys.stderr",
                },
                **(
                    {
                        "file": {
                            "class": "logging.FileHandler",
                            "level": "INFO",
                            "formatter": "file",
                            "filename": file_path,
                            "encoding": "utf-8",
                        }
                    }
                    if file_enabled
                    else {}
                ),
            },
            "root": {"level": "INFO", "handlers": ["console", "file"] if file_enabled else ["console"]},
            "loggers": {
                # Ensure library loggers propagate to root (no own handlers)
                "mcp": {"level": "INFO", "propagate": True, "handlers": []},
                "mini_codex": {"level": "INFO", "propagate": True, "handlers": []},
            },
        }
    )

    # Route structlog through stdlib, obeying the same handlers
    procs: list[Processor] = [structlog.processors.TimeStamper(fmt="iso"), structlog.processors.add_log_level]
    if os.getenv("MINICODEX_DEBUG"):
        procs.append(structlog.processors.JSONRenderer())
    else:
        procs.append(structlog.processors.KeyValueRenderer(key_order=["event"]))

    structlog.configure(
        processors=procs,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
