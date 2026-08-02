from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_bazel
from fastapi import HTTPException

from haku.console.config import NodeDaemonDefinition, NodeDaemonsConfig
from haku.console.conftest import console_sessions
from haku.console.node_daemon_models import NodeDaemonPresenceStatus
from haku.console.node_daemons import (
    ClaimRequest,
    ExecutionResultRequest,
    HeartbeatRequest,
    LeaseRequest,
    NodeDaemonService,
)


@pytest.fixture
def node_daemon_service(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> NodeDaemonService:
    monkeypatch.setenv("TEST_WYRM2_DAEMON_TOKEN", "wyrm2-secret")
    return NodeDaemonService(
        console_sessions(migrated_db_url),
        NodeDaemonsConfig(
            daemons={
                "wyrm2": NodeDaemonDefinition(
                    display_name="wyrm2", token_env_var="TEST_WYRM2_DAEMON_TOKEN", backends=["hostexec"]
                )
            }
        ),
    )


async def test_heartbeat_claim_lease_and_result_round_trip(node_daemon_service: NodeDaemonService) -> None:
    service = node_daemon_service
    instance_id = uuid4()
    await service.heartbeat(
        "wyrm2", HeartbeatRequest(instance_id=instance_id, version="test", backends=["hostexec"], capacity=1)
    )
    execution_id = await service.enqueue(daemon_id="wyrm2", backend="hostexec", payload={"cmd": "true"})
    claim = await service.claim("wyrm2", ClaimRequest(instance_id=instance_id, wait_seconds=0))
    assert claim is not None
    assert claim.execution_id == execution_id
    assert (await service.statuses()).daemons[0].status is NodeDaemonPresenceStatus.BUSY
    await service.renew("wyrm2", execution_id, LeaseRequest(instance_id=instance_id, lease_token=claim.lease_token))
    result = {"exit": {"kind": "exited", "exit_code": 0}, "stdout": "", "stderr": "", "duration_ms": 1}
    await service.finish(
        "wyrm2",
        execution_id,
        ExecutionResultRequest(
            instance_id=instance_id, lease_token=claim.lease_token, outcome="succeeded", result=result
        ),
    )
    # A daemon may retry after the console committed the result but its response was lost.
    await service.finish(
        "wyrm2",
        execution_id,
        ExecutionResultRequest(
            instance_id=instance_id, lease_token=claim.lease_token, outcome="succeeded", result=result
        ),
    )
    assert await service.wait(execution_id) == result


async def test_presence_uses_enum(node_daemon_service: NodeDaemonService) -> None:
    service = node_daemon_service
    assert (await service.statuses()).daemons[0].status is NodeDaemonPresenceStatus.OFFLINE


async def test_daemon_bearer_selects_identity(node_daemon_service: NodeDaemonService) -> None:
    service = node_daemon_service
    assert await service.authenticate("Bearer wyrm2-secret") == "wyrm2"
    with pytest.raises(HTTPException, match="invalid node daemon bearer"):
        await service.authenticate("Bearer wrong")


if __name__ == "__main__":
    pytest_bazel.main()
