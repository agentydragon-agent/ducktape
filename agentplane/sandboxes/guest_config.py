"""VM boot and capacity policy; Runner policy uses runner.configuration.Configuration."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentplane.runner.configuration import ResourceLimits


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
    """VM-only boot configuration, delivered beside the shared runner.json."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[3]
    resources: GuestResources
    console_autologin: bool = Field(default=False, description="Enable an unauthenticated root serial console.")
