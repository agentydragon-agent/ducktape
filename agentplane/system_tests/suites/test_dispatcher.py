"""Executable dispatcher scenarios sharing one k3s stack."""

from __future__ import annotations

import pytest
import pytest_bazel

from agentplane.system_tests.scenarios import dispatcher


@pytest.mark.timeout(600)
@pytest.mark.parametrize("replica_failover", [False, True], ids=["queue", "replicas"])
async def test_deployed_dispatcher_waits_for_ready_then_records_runner_admission(replica_failover: bool) -> None:
    await dispatcher.deployed_dispatcher_waits_for_ready_then_records_runner_admission(replica_failover)


@pytest.mark.timeout(600)
async def test_deployed_dispatcher_wakes_only_opted_in_sandbox_for_app_and_notification_sends() -> None:
    await dispatcher.deployed_dispatcher_wakes_only_opted_in_sandbox_for_app_and_notification_sends()


if __name__ == "__main__":
    pytest_bazel.main()
