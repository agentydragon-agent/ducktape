"""System scenarios sharing one sampler_vm k3s stack."""

import pytest
import pytest_bazel

from agentplane.system_tests.executor_environment import vm_executor as executor_environment
from agentplane.system_tests.scenarios.central_sampler import test_dispatcher_central_setup_tool_and_retained_answer

pytestmark = pytest.mark.vm_sandboxes

__all__ = ["executor_environment", "test_dispatcher_central_setup_tool_and_retained_answer"]

if __name__ == "__main__":
    pytest_bazel.main()
