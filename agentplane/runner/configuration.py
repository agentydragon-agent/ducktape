"""Runner's versioned file contract, shared by Pod and VM provisioning."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

CONFIG_DIRECTORY = "/run/agentplane/config"
CONFIG_FILE = f"{CONFIG_DIRECTORY}/runner.json"
LAUNCH_FILE = "/run/agentplane/sandbox/launch.json"
CA_BUNDLE = Path("/run/agentplane/trust/ca-certificates.crt")
JAVA_TRUST_STORE = "/run/agentplane/trust/ca-certificates.p12"
KUBECONFIG = f"{CONFIG_DIRECTORY}/kubeconfig"


class Endpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    target: str = Field(min_length=1, description="Service host:port.")
    bearer: str = Field(min_length=1, description="Bearer presented to the platform route.")


class ResourceLimits(BaseModel):
    """A cgroup-v2 budget; CPU quota is per fixed 100,000 microsecond period."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cpu_quota_micros: int = Field(gt=0)
    memory_max_bytes: int = Field(gt=0)
    pids_max: int = Field(gt=0)
    read_bps: int = Field(gt=0)
    write_bps: int = Field(gt=0)
    read_iops: int = Field(gt=0)
    write_iops: int = Field(gt=0)


class Cgroups(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    root: str
    agent_uid: int = Field(ge=1, le=4_294_967_295)
    agent_gid: int = Field(ge=1, le=4_294_967_295)
    block_devices: Sequence[str] = Field(min_length=1)
    aggregate: ResourceLimits
    process: ResourceLimits

    @model_validator(mode="after")
    def validate_limits(self) -> Cgroups:
        if not Path(self.root).is_absolute() or any(not Path(path).is_absolute() for path in self.block_devices):
            raise ValueError("cgroup and block-device paths must be absolute")
        if (
            self.process.memory_max_bytes > self.aggregate.memory_max_bytes
            or self.process.cpu_quota_micros > self.aggregate.cpu_quota_micros
            or self.process.pids_max > self.aggregate.pids_max
        ):
            raise ValueError("process memory, CPU and PID limits must fit aggregate")
        return self


class Environment(BaseModel):
    """Inherited names are read first; explicit values take precedence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    inherit: Sequence[str] = Field(default_factory=list)
    values: Mapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_names(self) -> Environment:
        if any(not name or "=" in name or "\0" in name for name in (*self.inherit, *self.values)):
            raise ValueError("environment names must be nonempty and contain neither '=' nor NUL")
        if any("\0" in value for value in self.values.values()):
            raise ValueError("environment values must not contain NUL")
        return self


class Harness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    binary: str
    base_url: str
    token_env: str = Field(min_length=1, description="Runner environment variable containing the provider token.")

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        url = AnyHttpUrl(value)
        if url.username is not None or url.password is not None or url.query or url.fragment or url.port == 0:
            raise ValueError("provider URL must not contain credentials, query, fragment, or port zero")
        return value.rstrip("/")

    @field_validator("binary")
    @classmethod
    def absolute_binary(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("harness executable must be absolute")
        return value


class Executor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    url: str

    @field_validator("url")
    @classmethod
    def loopback_endpoint(cls, value: str) -> str:
        endpoint = urlsplit(value)
        if (
            endpoint.scheme != "ws"
            or endpoint.hostname != "127.0.0.1"
            or not endpoint.port
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.path
            or endpoint.query
            or endpoint.fragment
            or "?" in value
            or "#" in value
        ):
            raise ValueError("executor URL must be ws://127.0.0.1:<nonzero port>")
        return value


class ContainerExecutor(Executor):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["container"] = "container"
    socket: str


class CgroupExecutor(Executor):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["cgroup"] = "cgroup"
    isolation: Cgroups


class DebugCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1)
    command_id: str = Field(min_length=1)


class Configuration(BaseModel):
    """All Runner policy supplied by its template, separate from Sandbox launch identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[1]
    state_dir: str
    workspace_root: str | None = None
    initialization_cwd: str
    control: Endpoint
    ingress: Endpoint
    platform_instructions: str = Field(min_length=1)
    runner_environment: Environment = Field(default_factory=Environment)
    harness_environment: Environment
    claude: Harness | None = None
    codex: Harness | None = None
    isolation: Cgroups | None = None
    executor: Annotated[ContainerExecutor | CgroupExecutor, Field(discriminator="kind")] | None = None
    debug_checkpoint: DebugCheckpoint | None = None

    @model_validator(mode="after")
    def valid_configuration(self) -> Configuration:
        if any(not Path(path).is_absolute() for path in (self.state_dir, self.initialization_cwd)):
            raise ValueError("state and initialization paths must be absolute")
        if self.workspace_root is not None and not Path(self.workspace_root).is_absolute():
            raise ValueError("workspace_root must be absolute when configured")
        if self.executor is not None and self.codex is None:
            raise ValueError("executor requires Codex")
        if isinstance(self.executor, ContainerExecutor) and (
            self.isolation is not None or not Path(self.executor.socket).is_absolute()
        ):
            raise ValueError("container executor requires an absolute socket and container-owned limits")
        if isinstance(self.executor, CgroupExecutor):
            if self.isolation is None:
                raise ValueError("cgroup executor requires harness cgroup isolation")
            root, executor_root = Path(self.isolation.root), Path(self.executor.isolation.root)
            if root == executor_root or root.parent != executor_root.parent:
                raise ValueError("executor and harness cgroups must be distinct siblings")
        return self
