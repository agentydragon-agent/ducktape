"""Explicit session management; runners retain launch specs, bootstrap results, and setup state."""

from pathlib import PurePosixPath

from google.protobuf.json_format import ParseDict

from agentplane.runner import protocol_pb2
from agentplane.runner.client import RunnerClient, RunnerError
from agentplane.sandbox_service.instructions import combine_instructions
from agentplane.sandbox_service.models import SessionDestination
from agentplane.sandbox_service.session_config import SandboxBinding

# gazelle:include_dep @pypi//protobuf


def launch_spec(
    destination: SessionDestination,
    overrides: dict[str, object],
    *,
    binding: SandboxBinding | None,
    platform_instructions: str,
) -> protocol_pb2.SessionSpec:
    defaults = binding.thread_defaults if binding is not None else None
    values = defaults.proto_json(destination.session_id) if defaults is not None else {}
    spec = ParseDict(values | overrides, protocol_pb2.SessionSpec())
    validate_spec(spec)
    context = (
        "Your explicit Sandbox Service session destination is:\n"
        f"{destination.model_dump_json()}\n"
        "Use these identifiers when addressing this session; they are not credentials."
    )
    spec.instructions = combine_instructions(combine_instructions(platform_instructions, context), spec.instructions)
    return spec


def validate_spec(spec: protocol_pb2.SessionSpec) -> None:
    if spec.harness not in (protocol_pb2.HARNESS_CLAUDE, protocol_pb2.HARNESS_CODEX) or not spec.cwd or not spec.model:
        raise ValueError("a supported harness, cwd, and model are required")
    if not PurePosixPath(spec.cwd).is_absolute():
        raise ValueError("cwd must be absolute")


async def initialize(client: RunnerClient, binding: SandboxBinding | None) -> protocol_pb2.InitializeResult:
    if binding is None or not binding.bootstrap:
        raise RunnerError("this Sandbox has no configured bootstrap")
    return await client.initialize(binding.bootstrap)


async def open_session(
    client: RunnerClient,
    destination: SessionDestination,
    spec: protocol_pb2.SessionSpec,
    *,
    binding: SandboxBinding | None,
    setup_script: str | None,
) -> protocol_pb2.Attached:
    if binding is not None:
        if binding.bootstrap:
            result = await initialize(client, binding)
            if result.exit_code != 0:
                raise RunnerError("Sandbox bootstrap failed; no session was opened")
        if setup_script is None and binding.thread_defaults is not None:
            setup_script = binding.thread_defaults.setup_script
    attachment = await client.attach(destination.session_id, spec=spec, setup_script=setup_script)
    try:
        return attachment.attached
    finally:
        attachment.cancel()


async def resume_session(client: RunnerClient, session_id: str) -> protocol_pb2.Attached:
    # Never assemble a new spec from today's configuration. No retained session means no resume.
    summary = next((row for row in await client.list_sessions() if row.session_id == session_id), None)
    if summary is None:
        raise RunnerError("runner has no retained session to resume")
    if summary.setup_state in (protocol_pb2.SETUP_STATE_FAILED, protocol_pb2.SETUP_STATE_INTERRUPTED):
        raise RunnerError("session setup failed or was interrupted; create a new session")
    try:
        validate_spec(summary.spec)
    except ValueError as error:
        raise RunnerError("runner session has no recoverable spec") from error
    attachment = await client.attach(session_id, spec=summary.spec)
    try:
        return attachment.attached
    finally:
        attachment.cancel()
