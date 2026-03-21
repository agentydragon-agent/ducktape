"""Prompt loading helpers for the twenty questions eval.

Loads shared prompt templates from text files via Bazel runfiles, providing a
single source of truth used by all implementations (Python, Rust, Go).
"""

from util.bazel.runfiles import get_required_path

_SIM_RLOCATION = "_main/skills/info_gathering/evals/twenty_questions/sim.txt"
_SKILL_RLOCATION = "_main/skills/info_gathering/SKILL.md"
_SCRATCH_NOTE_RLOCATION = "_main/skills/info_gathering/evals/twenty_questions/scratch_system_note.txt"
_FIRST_USER_MSG_RLOCATION = "_main/skills/info_gathering/evals/twenty_questions/first_user_message.txt"


def load_sim_prompt(*, secret: str, turn_limit: int) -> str:
    template = get_required_path(_SIM_RLOCATION).read_text()
    return template.format(secret=secret, turn_limit=turn_limit)


def load_skill_prompt() -> str:
    return get_required_path(_SKILL_RLOCATION).read_text()


def load_scratch_system_note() -> str:
    return get_required_path(_SCRATCH_NOTE_RLOCATION).read_text().strip()


def build_guesser_system(skill_text: str) -> str:
    scratch_note = load_scratch_system_note()
    return (
        "Follow this information-gathering skill throughout.\n\n"
        f"<skill>\n{skill_text}\n</skill>\n\n"
        f"---\n\n{scratch_note}"
    )


def first_user_message(domain_description: str, turn_limit: int) -> str:
    template = get_required_path(_FIRST_USER_MSG_RLOCATION).read_text().strip()
    return template.format(domain_description=domain_description, turn_limit=turn_limit)
