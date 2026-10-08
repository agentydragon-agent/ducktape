"""Sandbox Service's independent, image-owned Session history schema."""

from pathlib import Path

from agentplane.sandbox_service.session_history.db import Base
from util.db_migrations import MigrationRunner

RUNNER = MigrationRunner(
    metadata=Base.metadata, migrations_dir=Path(__file__).parent / "migrations", lock_key=0x53415243
)
