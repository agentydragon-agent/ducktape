"""Typed service protobuf boundary; persisted Kubernetes/app JSON formats stay unchanged."""

from google.protobuf.json_format import MessageToDict, ParseDict

from agentplane.runner import protocol_pb2 as runner_pb2
from agentplane.sandbox_service import protocol_pb2
from agentplane.sandbox_service.destinations import SandboxDestination, SessionDestination
from agentplane.sandbox_service.inventory import NewSandbox, SandboxView

# gazelle:include_dep @pypi//protobuf


def sandbox_destination(value: protocol_pb2.SandboxDestination) -> SandboxDestination:
    return SandboxDestination.model_validate(MessageToDict(value, preserving_proto_field_name=True))


def session_destination(value: protocol_pb2.SessionDestination) -> SessionDestination:
    return SessionDestination(**sandbox_destination(value.sandbox).model_dump(), session_id=value.session_id)


def destination_proto(value: SandboxDestination) -> protocol_pb2.SandboxDestination:
    return ParseDict(value.model_dump(mode="json", exclude={"session_id"}), protocol_pb2.SandboxDestination())


def session_proto(value: SandboxDestination, session_id: str) -> protocol_pb2.SessionDestination:
    return protocol_pb2.SessionDestination(sandbox=destination_proto(value), session_id=session_id)


def sandbox_proto(value: SandboxView) -> protocol_pb2.Sandbox:
    return ParseDict(value.model_dump(mode="json", exclude_none=True), protocol_pb2.Sandbox())


def sandbox_view(value: protocol_pb2.Sandbox) -> SandboxView:
    data = MessageToDict(value, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)
    # These existing persisted/UI models require the key even when Kubernetes has no value.
    data.setdefault("kubernetes_grant_error", None)
    if "pod" in data:
        for field in ("phase", "ip", "node_name"):
            data["pod"].setdefault(field, None)
    return SandboxView.model_validate(data)


def new_sandbox(value: protocol_pb2.CreateSandboxRequest) -> NewSandbox:
    return NewSandbox.model_validate(
        MessageToDict(value, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)
    )


def create_proto(value: NewSandbox) -> protocol_pb2.CreateSandboxRequest:
    return ParseDict(value.model_dump(mode="json", exclude_none=True), protocol_pb2.CreateSandboxRequest())


def launch_overrides(request: protocol_pb2.OpenSessionRequest) -> dict[str, object]:
    paths = list(request.override_mask.paths)
    fields = runner_pb2.SessionSpec.DESCRIPTOR.fields_by_name
    if len(set(paths)) != len(paths) or any(path not in fields for path in paths):
        raise ValueError("override_mask must contain unique SessionSpec field names")
    if any(field.name not in paths for field, _ in request.spec.ListFields()):
        raise ValueError("every supplied SessionSpec field must be selected by override_mask")
    # Use JSON field names here to match the existing stored default overlay. The service wire
    # itself carries the native protobuf, including an explicit mask for default/empty values.
    values = MessageToDict(request.spec, always_print_fields_with_no_presence=True)
    return {fields[path].json_name: values[fields[path].json_name] for path in paths}


def open_proto(
    destination: protocol_pb2.SessionDestination, overrides: dict[str, object], setup_script: str | None
) -> protocol_pb2.OpenSessionRequest:
    fields = runner_pb2.SessionSpec.DESCRIPTOR.fields
    if any(
        field.name != field.json_name and field.name in overrides and field.json_name in overrides for field in fields
    ):
        raise ValueError("a SessionSpec field cannot use both proto and JSON spellings")
    spec = ParseDict(overrides, runner_pb2.SessionSpec())
    paths = [field.name for field in fields if field.name in overrides or field.json_name in overrides]
    request = protocol_pb2.OpenSessionRequest(destination=destination, spec=spec, setup_script=setup_script)
    request.override_mask.paths.extend(paths)
    return request
