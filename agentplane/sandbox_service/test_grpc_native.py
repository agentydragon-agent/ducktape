"""Production gRPC client → workload auth/discovery → both real harnesses, without the app."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_bazel
from google.protobuf.json_format import MessageToDict
from kubernetes_asyncio import client as k8s_client

from agentplane.protocol import command_pb2, event_log_pb2
from agentplane.runner import protocol_pb2 as runner_pb2
from agentplane.runner.client import RunnerError, StreamClosedError
from agentplane.runner.conftest import RunnerHandle
from agentplane.runner.testing import events
from agentplane.runner.testing.scripted_model import ScriptedModel, Text
from agentplane.sandbox_service.client import SandboxServiceClient
from agentplane.sandbox_service.destinations import DestinationResolver, SandboxDestination
from agentplane.sandbox_service.grpc_api import Resources
from agentplane.sandbox_service.testing.grpc_service import service
from agentplane.sandbox_service.testing.kubernetes import ACCOUNT, SANDBOX, SANDBOX_UID, Cluster
from agentplane.subjects import ServiceAccountRef
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE, TokenVerdict
from agentplane.workload_auth.principal import WorkloadPrincipalResolver

# gazelle:include_dep @pypi//protobuf

OWNER = ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name=ACCOUNT)
DESTINATION = SandboxDestination(owner=OWNER, sandbox=SANDBOX, sandbox_uid=SANDBOX_UID)


@pytest.fixture
async def remote(cluster: Cluster, runner: RunnerHandle, tmp_path: Path) -> AsyncIterator[SandboxServiceClient]:
    token = "test-native-grpc-token"
    audience = "test-native-grpc"
    cluster.fake.tokens[token] = TokenVerdict(
        username=f"system:serviceaccount:{OWNER.namespace}:{OWNER.name}",
        pod_name="test-native-caller", pod_uid="test-native-caller-uid", audiences=(audience,),
    )
    token_file = tmp_path / "service-token"
    token_file.write_text(token)
    resources = Resources(
        principals=WorkloadPrincipalResolver(
            authentication=k8s_client.AuthenticationV1Api(cluster.api), audience=audience,
            allowed_service_account_namespaces={SANDBOX_NAMESPACE},
        ),
        destinations=DestinationResolver(cluster.inventory, k8s_client.CoreV1Api(cluster.api), runner.port),
        manager_accounts=frozenset({OWNER}), platform_instructions="Test backend-owned guidance.",
    )
    async with service(resources) as target:
        client = SandboxServiceClient(target, namespace=SANDBOX_NAMESPACE, token_file=token_file)
        try:
            yield client
        finally:
            await client.close()


async def test_open_admit_replay_follow_stop_and_resume(
    remote: SandboxServiceClient, model: ScriptedModel, spec: runner_pb2.SessionSpec,
) -> None:
    runner = remote.runner(DESTINATION)
    opened = await runner.open("grpc-session", MessageToDict(spec))
    assert opened.harness_state == runner_pb2.HARNESS_STATE_RUNNING
    assert "Test backend-owned guidance." in opened.spec.instructions
    assert str(SANDBOX_UID) in opened.spec.instructions
    assert (await runner.list_sessions())[0].spec == opened.spec
    command = command_pb2.Command(command_id="grpc-notice", submit_input=command_pb2.SubmitInput(text="Reply: GRPC_OK"))
    receipt = await runner.command("grpc-session", command, after_cursor=0)
    assert receipt.event.command_admitted.command == command
    # Neither admission nor exact receipt replay waits for model completion.
    assert await runner.command("grpc-session", command, after_cursor=0) == receipt
    await model.reply(await model.request(), Text("GRPC_OK"))
    attachment = await runner.attach("grpc-session")
    entries: list[event_log_pb2.EventEntry] = []
    try:
        async with asyncio.timeout(20):
            while True:
                entry = await attachment.next_entry()
                entries.append(entry)
                if events.turn_completed(entry):
                    break
    finally:
        attachment.cancel()
    assert events.of_kind(entries, "command_admitted") == [receipt]
    assert any(command.command_id in e.event.harness_user_message_confirmed.origin_command_ids
               for e in events.of_kind(entries, "harness_user_message_confirmed"))
    stop = command_pb2.Command(command_id="grpc-stop", stop_runner_session=command_pb2.StopRunnerSession())
    await runner.command("grpc-session", stop, after_cursor=entries[-1].cursor)
    tail = await runner.attach("grpc-session", after_cursor=entries[-1].cursor)
    try:
        async with asyncio.timeout(20):
            while True:
                try:
                    entry = await tail.next_entry()
                except StreamClosedError:
                    break
                assert entry.cursor > entries[-1].cursor
    finally:
        tail.cancel()
    with pytest.raises(RunnerError):
        await runner.command("grpc-session", command_pb2.Command(
            command_id="no-wake", submit_input=command_pb2.SubmitInput(text="no wake"),
        ), after_cursor=0)
    assert (await runner.list_sessions())[0].harness_state == runner_pb2.HARNESS_STATE_STOPPED
    resumed = await runner.resume("grpc-session")
    assert resumed.spec == opened.spec
    assert resumed.harness_state == runner_pb2.HARNESS_STATE_RUNNING


async def test_observe_and_command_do_not_create_unknown_session(remote: SandboxServiceClient) -> None:
    runner = remote.runner(DESTINATION)
    with pytest.raises(RunnerError):
        await runner.attach("unknown")
    with pytest.raises(RunnerError):
        await runner.command("unknown", command_pb2.Command(
            command_id="unknown-notice", submit_input=command_pb2.SubmitInput(text="no creation"),
        ), after_cursor=0)
    assert not await runner.list_sessions()


if __name__ == "__main__":
    pytest_bazel.main()
