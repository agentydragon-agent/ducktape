"""System scenarios sharing one vm k3s stack."""

import pytest
import pytest_bazel

from agentplane.system_tests.scenarios.runner_credentials import test_vm_mtls_certificates_authenticate_both_harnesses
from agentplane.system_tests.scenarios.vm_sandbox import test_vm_sandbox_scenarios

pytestmark = pytest.mark.vm_sandboxes

__all__ = ["test_vm_mtls_certificates_authenticate_both_harnesses", "test_vm_sandbox_scenarios"]

if __name__ == "__main__":
    pytest_bazel.main()
