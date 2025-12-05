"""Critic system prompt utilities."""

from __future__ import annotations

from importlib import resources

# Critic prompts directory
_PROMPTS_DIR = resources.files("adgn.props").joinpath("critic/prompts")


def list_critic_system_prompts() -> list[str]:
    """List all critic system prompt files (.md) in critic/prompts/."""
    return sorted(item.name for item in _PROMPTS_DIR.iterdir() if item.is_file() and item.name.endswith(".md"))


def get_critic_system_prompt_path(filename: str):
    """Get the path object for a critic system prompt file."""
    return _PROMPTS_DIR.joinpath(filename)
