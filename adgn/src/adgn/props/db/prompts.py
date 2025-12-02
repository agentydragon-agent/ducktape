"""Prompt-related database operations."""

from __future__ import annotations

import hashlib
from importlib import resources
from uuid import UUID

from adgn.props.db import get_session
from adgn.props.db.models import Prompt

# Shared constant for detector directory
_DETECTOR_DIR = resources.files("adgn.props").joinpath("prompts/system")


def hash_and_upsert_prompt(
    prompt_text: str, prompt_optimization_run_id: UUID | None = None, template_file_path: str | None = None
) -> str:
    """Compute SHA-256 hash of prompt text and upsert to database.

    Args:
        prompt_text: The prompt content to hash and store
        prompt_optimization_run_id: Optional ID of the optimization run that generated this prompt
        template_file_path: Optional template filename (relative path only, e.g., 'dead_code.md')

    Returns:
        The computed SHA-256 hash.
    """
    prompt_sha256 = hashlib.sha256(prompt_text.encode()).hexdigest()
    with get_session() as session:
        prompt_obj = Prompt(
            prompt_sha256=prompt_sha256,
            prompt_text=prompt_text,
            prompt_optimization_run_id=prompt_optimization_run_id,
            template_file_path=template_file_path,
        )
        session.merge(prompt_obj)
        session.flush()
    return prompt_sha256


def load_and_upsert_detector_prompt(filename: str) -> str:
    """Load detector .md file and upsert with filename as template_file_path."""
    return hash_and_upsert_prompt(
        _DETECTOR_DIR.joinpath(filename).read_text(encoding="utf-8"), template_file_path=filename
    )


def discover_detector_prompts() -> list[str]:
    """Auto-discover all .md files in prompts/system/ (returns filenames only)."""
    return sorted(item.name for item in _DETECTOR_DIR.iterdir() if item.is_file() and item.name.endswith(".md"))
