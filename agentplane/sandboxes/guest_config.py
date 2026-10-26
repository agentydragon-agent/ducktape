"""Public guest configuration shared by VM generation and the test-only Python reference runner."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

CA_BUNDLE = Path("/run/agentplane/ca-certificates.crt")


class Endpoint(BaseModel):
    """A service the guest runner dials through `proxy_url`."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    target: str = Field(min_length=1, description="host:port to dial.")
    bearer: str = Field(min_length=1, description="Placeholder the egress proxy swaps for the guest's token.")


class ResourceLimits(BaseModel):
    """One cgroup-v2 budget. CPU quota is microseconds per a fixed 100,000 µs period."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cpu_quota_micros: int = Field(gt=0)
    memory_max_bytes: int = Field(gt=0)
    pids_max: int = Field(gt=0)
    read_bps: int = Field(gt=0)
    write_bps: int = Field(gt=0)
    read_iops: int = Field(gt=0)
    write_iops: int = Field(gt=0)


class GuestResources(BaseModel):
    """VM size, systemd service caps, and the delegated Runner cgroup budgets."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    guest_memory_bytes: int = Field(gt=0)
    guest_vcpu_count: int = Field(gt=0)
    os_reserve_bytes: int = Field(ge=0)
    service_memory_high_bytes: int = Field(gt=0)
    service_memory_max_bytes: int = Field(gt=0)
    service_cpu_quota_micros: int = Field(gt=0)
    service_pids_max: int = Field(gt=0)
    aggregate: ResourceLimits
    process: ResourceLimits
    executor: ResourceLimits | None = None

    @model_validator(mode="after")
    def internally_consistent(self) -> GuestResources:
        if self.os_reserve_bytes >= self.guest_memory_bytes:
            raise ValueError("os_reserve_bytes must be smaller than guest_memory_bytes")
        if self.service_memory_high_bytes > self.service_memory_max_bytes:
            raise ValueError("service_memory_high_bytes must not exceed service_memory_max_bytes")
        if self.service_memory_max_bytes > self.guest_memory_bytes - self.os_reserve_bytes:
            raise ValueError("service_memory_max_bytes must leave the configured OS reserve")
        if self.aggregate.memory_max_bytes > self.service_memory_high_bytes:
            raise ValueError("aggregate memory max must not exceed service memory high")
        if self.aggregate.cpu_quota_micros > self.service_cpu_quota_micros:
            raise ValueError("aggregate CPU quota must not exceed service CPU quota")
        if self.aggregate.pids_max > self.service_pids_max:
            raise ValueError("aggregate PID max must not exceed service PID max")
        if self.executor is not None:
            if self.executor.memory_max_bytes > self.service_memory_high_bytes - self.aggregate.memory_max_bytes:
                raise ValueError("harness and executor memory caps must fit below service memory high")
            if self.executor.pids_max >= self.service_pids_max - self.aggregate.pids_max:
                raise ValueError("harness and executor PID caps must leave room for Runner and supervisors")
            if self.executor.cpu_quota_micros > self.service_cpu_quota_micros:
                raise ValueError("executor CPU quota must fit within Runner service quota")
        if self.process.memory_max_bytes > self.aggregate.memory_max_bytes:
            raise ValueError("process memory max must not exceed aggregate memory max")
        if self.process.cpu_quota_micros > self.aggregate.cpu_quota_micros:
            raise ValueError("process CPU quota must not exceed aggregate CPU quota")
        if self.process.pids_max > self.aggregate.pids_max:
            raise ValueError("process PID max must not exceed aggregate PID max")
        if self.service_cpu_quota_micros > self.guest_vcpu_count * 100_000:
            raise ValueError("service CPU quota must not exceed guest vCPU capacity")
        if self.service_cpu_quota_micros % 1_000 != 0:
            raise ValueError("service CPU quota must convert to an integral systemd CPUQuota percent")
        return self


class GuestConfig(BaseModel):
    """Public per-environment launch values delivered on the ConfigMap disk."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[2]
    control: Endpoint
    ingress: Endpoint
    resources: GuestResources
    llm_base_url: AnyHttpUrl
    proxy_url: AnyHttpUrl
    platform_instructions: str = Field(min_length=1, description="Standing instructions for every Session.")
    console_autologin: bool = Field(
        default=False,
        description="Whether the serial console is a root shell without a login (vm.nix reads this field).",
    )
    harness_env: Mapping[str, str] | None = Field(
        default=None,
        description="Environment added to every harness process. The runner refuses a name the guest owns "
        "(PATH, HOME, the proxy and CA variables).",
    )

    @field_validator("llm_base_url", "proxy_url")
    @classmethod
    def http_origin(cls, value: AnyHttpUrl, info: ValidationInfo) -> AnyHttpUrl:
        if (
            value.username is not None
            or value.password is not None
            or value.path not in {None, "/"}
            or value.query
            or value.fragment
            or value.port == 0
        ):
            raise ValueError(f"{info.field_name} must be an HTTP(S) origin URL")
        return value

    @field_serializer("llm_base_url", "proxy_url", when_used="json")
    def serialize_origin(self, value: AnyHttpUrl) -> str:
        return str(value).rstrip("/")
