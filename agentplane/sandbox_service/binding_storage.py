"""Retain the pre-cutover annotation spelling so old-app rollback remains possible."""

import json

from google.protobuf.json_format import MessageToDict, ParseDict

from agentplane.sandbox_service.protocol_pb2 import SandboxBinding

# gazelle:include_dep @pypi//protobuf


def read_binding(raw: str) -> SandboxBinding:
    data = json.loads(raw)
    if "thread_defaults" in data:
        data["session_defaults"] = data.pop("thread_defaults")
    return ParseDict(data, SandboxBinding())


def write_binding(binding: SandboxBinding) -> str:
    data = MessageToDict(binding, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)
    if "session_defaults" in data:
        data["thread_defaults"] = data.pop("session_defaults")
    return json.dumps(data)
