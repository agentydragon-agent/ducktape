"""Keep persisted launch bindings readable by the pre-cutover app during rollback.

Only this annotation codec knows the legacy field name. Service and browser APIs use
session_defaults; writing a binding must not silently migrate staging's stored format.
"""

from pydantic import Field

from agentplane.sandbox_service.session_config import SandboxBinding, SessionDefaults


class _StoredBinding(SandboxBinding):
    session_defaults: SessionDefaults | None = Field(default=None, alias="thread_defaults")


def read_binding(raw: str) -> SandboxBinding:
    return SandboxBinding.model_validate(_StoredBinding.model_validate_json(raw).model_dump())


def write_binding(binding: SandboxBinding) -> str:
    return _StoredBinding(thread_defaults=binding.session_defaults, bootstrap=binding.bootstrap).model_dump_json(
        by_alias=True, exclude_none=True
    )
