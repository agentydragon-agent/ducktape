"""System scenarios sharing one vm_systemd k3s stack."""

import pytest_bazel

from agentplane.system_tests.scenarios.runner_systemd import test_real_systemd_supervision

__all__ = ["test_real_systemd_supervision"]

if __name__ == "__main__":
    pytest_bazel.main()
