"""System scenarios sharing one pod k3s stack."""

import pytest_bazel

from agentplane.system_tests.scenarios.dispatcher import (
    test_deployed_dispatcher_waits_for_ready_then_records_runner_admission,
    test_deployed_dispatcher_wakes_only_opted_in_sandbox_for_app_and_notification_sends,
)

__all__ = [
    "test_deployed_dispatcher_waits_for_ready_then_records_runner_admission",
    "test_deployed_dispatcher_wakes_only_opted_in_sandbox_for_app_and_notification_sends",
]

if __name__ == "__main__":
    pytest_bazel.main()
