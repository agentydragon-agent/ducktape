"""System scenarios sharing one real_model k3s stack."""

import pytest_bazel

from agentplane.system_tests.scenarios.egress import (
    test_a_bound_sandbox_reaches_what_its_policy_names_and_nothing_else,
    test_a_policy_granted_after_the_sandbox_is_running_takes_effect,
    test_the_model_call_itself_goes_through_the_proxy,
)
from agentplane.system_tests.scenarios.session_instructions import (
    test_the_model_obeys_the_standing_instruction_its_session_was_opened_with,
    test_the_standing_instruction_reaches_the_model_and_only_in_its_own_session,
)

__all__ = [
    "test_a_bound_sandbox_reaches_what_its_policy_names_and_nothing_else",
    "test_a_policy_granted_after_the_sandbox_is_running_takes_effect",
    "test_the_model_call_itself_goes_through_the_proxy",
    "test_the_model_obeys_the_standing_instruction_its_session_was_opened_with",
    "test_the_standing_instruction_reaches_the_model_and_only_in_its_own_session",
]

if __name__ == "__main__":
    pytest_bazel.main()
