"""Prompt-related database operations."""

from __future__ import annotations

import hashlib
from uuid import UUID

from adgn.props.critic.prompts import get_critic_system_prompt_path
from adgn.props.db import get_session
from adgn.props.db.models import Prompt


def hash_and_upsert_prompt(
    prompt_text: str, prompt_optimization_run_id: UUID | None = None, template_file_path: str | None = None
) -> str:
    """Compute SHA-256 hash of prompt text and upsert to database.

    Opens its own session internally (legacy interface for backward compatibility).

    Args:
        prompt_text: The prompt content to hash and store
        prompt_optimization_run_id: Optional ID of the optimization run that generated this prompt
        template_file_path: Optional template filename (relative path only, e.g., 'dead_code.md')

    Returns:
        The computed SHA-256 hash.
    """
    prompt_sha256 = hashlib.sha256(prompt_text.encode()).hexdigest()
    with get_session() as session:
        _upsert_prompt_with_session(session, prompt_sha256, prompt_text, prompt_optimization_run_id, template_file_path)
    return prompt_sha256


def _upsert_prompt_with_session(
    session,
    prompt_sha256: str,
    prompt_text: str,
    prompt_optimization_run_id: UUID | None,
    template_file_path: str | None,
) -> None:
    """Internal helper to upsert prompt within an existing session."""
    prompt_obj = Prompt(
        prompt_sha256=prompt_sha256,
        prompt_text=prompt_text,
        prompt_optimization_run_id=prompt_optimization_run_id,
        template_file_path=template_file_path,
    )
    session.merge(prompt_obj)
    session.flush()


def load_and_upsert_detector_prompt(filename: str) -> str:
    """Load critic system prompt .md file and upsert with filename as template_file_path.

    Opens its own session internally (legacy interface for backward compatibility).
    """
    return hash_and_upsert_prompt(
        get_critic_system_prompt_path(filename).read_text(encoding="utf-8"), template_file_path=filename
    )


def load_and_upsert_detector_prompt_with_session(session, filename: str) -> str:
    """Load critic system prompt .md file and upsert using provided session.

    Args:
        session: Active database session
        filename: Critic system prompt filename (e.g., 'dead_code.md')

    Returns:
        The computed SHA-256 hash
    """
    prompt_text = get_critic_system_prompt_path(filename).read_text(encoding="utf-8")
    prompt_sha256 = hashlib.sha256(prompt_text.encode()).hexdigest()
    _upsert_prompt_with_session(session, prompt_sha256, prompt_text, None, filename)
    return prompt_sha256
