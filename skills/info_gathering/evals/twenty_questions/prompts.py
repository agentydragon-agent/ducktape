"""Prompt loading helpers for the twenty questions eval.

Loads shared prompt templates from text files via Bazel runfiles, providing a
single source of truth used by all implementations (Python, Rust, Go).
"""

from util.bazel.runfiles import get_required_path

_SIM_RLOCATION = "_main/skills/info_gathering/evals/twenty_questions/sim.txt"
_SKILL_RLOCATION = "_main/skills/info_gathering/SKILL.md"
_SCRATCH_NOTE_RLOCATION = "_main/skills/info_gathering/evals/twenty_questions/scratch_system_note.txt"
_FIRST_USER_MSG_RLOCATION = "_main/skills/info_gathering/evals/twenty_questions/first_user_message.txt"

_BASE_GUESSER_PREAMBLE = (
    "You are playing 20 Questions. Your goal is to identify the secret in as few questions as possible."
)


def load_sim_prompt(*, secret: str, turn_limit: int) -> str:
    template = get_required_path(_SIM_RLOCATION).read_text()
    return template.format(secret=secret, turn_limit=turn_limit)


def load_skill_prompt() -> str:
    return get_required_path(_SKILL_RLOCATION).read_text()


def load_scratch_system_note() -> str:
    return get_required_path(_SCRATCH_NOTE_RLOCATION).read_text().strip()


def build_guesser_system(*, skill: str, has_scratch: bool) -> str:
    """Compose the guesser's system prompt from independent pieces.

    Args:
        skill: Skill text to include. Empty string = no skill.
        has_scratch: Include the scratch container exec tool note.
    """
    parts: list[str] = [_BASE_GUESSER_PREAMBLE]

    if skill:
        parts.append(f"Follow this information-gathering skill throughout.\n\n<skill>\n{skill}\n</skill>")

    if has_scratch:
        parts.append(load_scratch_system_note())

    return "\n\n---\n\n".join(parts)


def first_user_message(domain_description: str, turn_limit: int) -> str:
    template = get_required_path(_FIRST_USER_MSG_RLOCATION).read_text().strip()
    return template.format(domain_description=domain_description, turn_limit=turn_limit)
