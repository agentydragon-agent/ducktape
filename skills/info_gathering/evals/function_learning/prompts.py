"""Prompt loading helpers for the function learning eval."""

from skills.info_gathering.evals.function_learning.functions import SecretFunction
from skills.info_gathering.evals.twenty_questions.prompts import load_scratch_system_note
from util.bazel.runfiles import get_required_path

_FIRST_USER_MSG_RLOCATION = "_main/skills/info_gathering/evals/function_learning/first_user_message.txt"

_BASE_PREAMBLE = (
    "You are playing a function-learning game. There is a secret boolean function "
    "f: {0,1}^N -> {0,1}^M. Each turn, you query one input and submit a Python program "
    "that implements your current best guess for f. Your goal is to minimize total "
    "Hamming loss (sum of bit disagreements across all possible inputs) summed over all turns."
)


def build_system_prompt(*, skill: str, has_scratch: bool) -> str:
    """Compose the system prompt for the function learning guesser."""
    parts: list[str] = [_BASE_PREAMBLE]

    if skill:
        parts.append(f"Follow this information-gathering skill throughout.\n\n<skill>\n{skill}\n</skill>")

    if has_scratch:
        parts.append(load_scratch_system_note())

    return "\n\n---\n\n".join(parts)


def first_user_message(fn: SecretFunction, turn_limit: int, function_description: str) -> str:
    template = get_required_path(_FIRST_USER_MSG_RLOCATION).read_text().strip()
    return template.format(
        n_bits=fn.n, m_bits=fn.m, n_inputs=2**fn.n, turn_limit=turn_limit, function_description=function_description
    )
