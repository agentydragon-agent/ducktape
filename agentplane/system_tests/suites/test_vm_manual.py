"""System scenarios sharing one vm k3s stack."""

import pytest
import pytest_bazel

from agentplane.system_tests.executor_environment import vm_executor as executor_environment
from agentplane.system_tests.scenarios.storage import test_fresh_workspace_storage_survives_replacement
from agentplane.system_tests.scenarios.suspend_resume import (
    test_two_harness_threads_keep_their_context_after_sandbox_suspend_resume,
)
from agentplane.system_tests.scenarios.vm_workspace_ownership import (
    test_fresh_vm_session_workspace_is_created_for_harness_identity,
)

pytestmark = pytest.mark.vm_sandboxes

__all__ = [
    "executor_environment",
    "test_fresh_vm_session_workspace_is_created_for_harness_identity",
    "test_fresh_workspace_storage_survives_replacement",
    "test_two_harness_threads_keep_their_context_after_sandbox_suspend_resume",
]

if __name__ == "__main__":
    pytest_bazel.main()
