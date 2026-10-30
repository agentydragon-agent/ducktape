"""System scenarios sharing one sampler_vm k3s stack."""

import pytest_bazel

from agentplane.system_tests.scenarios.central_sampler import (
    test_dispatcher_central_setup_tool_and_retained_answer,
    test_dispatcher_central_setup_tool_and_retained_answer_vm,
)

__all__ = [
    "test_dispatcher_central_setup_tool_and_retained_answer",
    "test_dispatcher_central_setup_tool_and_retained_answer_vm",
]

if __name__ == "__main__":
    pytest_bazel.main()
