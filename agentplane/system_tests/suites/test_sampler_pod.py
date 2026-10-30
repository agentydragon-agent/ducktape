"""System scenarios sharing one sampler_pod k3s stack."""

import pytest_bazel

from agentplane.system_tests.executor_environment import pod_executor, sampler_pod_executor as executor_environment
from agentplane.system_tests.scenarios.central_sampler import test_dispatcher_central_setup_tool_and_retained_answer

__all__ = ["executor_environment", "pod_executor", "test_dispatcher_central_setup_tool_and_retained_answer"]

if __name__ == "__main__":
    pytest_bazel.main()
