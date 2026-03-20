"""Prompt loading helpers referencing the original eval prompt files."""

from util.bazel.runfiles import get_required_path

_SIM_RLOCATION = "_main/skills/info_gathering/evals/twenty_questions/sim.txt"
_SKILL_RLOCATION = "_main/skills/info_gathering/SKILL.md"

_SCRATCH_SYSTEM_NOTE = """\
You have access to an `exec` tool — a private Docker container for scratch computation. \
Use it freely: run code, track hypothesis spaces, write notes, organize your reasoning. \
Calling this tool does NOT use up one of your question turns."""


def load_sim_prompt(*, secret: str, turn_limit: int) -> str:
    template = get_required_path(_SIM_RLOCATION).read_text()
    return template.format(secret=secret, turn_limit=turn_limit)


def load_skill_prompt() -> str:
    return get_required_path(_SKILL_RLOCATION).read_text()


def build_guesser_system(skill_text: str) -> str:
    return (
        "Follow this information-gathering skill throughout.\n\n"
        f"<skill>\n{skill_text}\n</skill>\n\n"
        f"---\n\n{_SCRATCH_SYSTEM_NOTE}"
    )


def first_user_message(domain_description: str, turn_limit: int) -> str:
    return (
        f"Play 20 Questions. I'm thinking of {domain_description}. "
        f"You have {turn_limit} yes/no questions. "
        "When confident, state: 'My answer is: [X]'."
    )
