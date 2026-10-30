"""System scenarios sharing one vm k3s stack."""

import pytest_bazel

from agentplane.system_tests.scenarios.runner_credentials import (
    test_cert_manager_reissues_a_deleted_tls_secret,
    test_pod_mtls_session_survives_replacement_and_keeps_history,
    test_vm_mtls_certificates_authenticate_both_harnesses,
)
from agentplane.system_tests.scenarios.vm_sandbox import test_vm_sandbox_scenarios

__all__ = [
    "test_cert_manager_reissues_a_deleted_tls_secret",
    "test_pod_mtls_session_survives_replacement_and_keeps_history",
    "test_vm_mtls_certificates_authenticate_both_harnesses",
    "test_vm_sandbox_scenarios",
]

if __name__ == "__main__":
    pytest_bazel.main()
