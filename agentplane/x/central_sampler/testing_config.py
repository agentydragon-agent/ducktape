"""Typed fixture configuration for the separately executed Go sampler."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str
    credential: SecretStr
    models: set[str] = Field(min_length=1)
    reasoning_efforts: set[str] = Field(min_length=1)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_url: str
    listen: str
    service_name: str
    providers: dict[str, Provider] = Field(min_length=1)
    audience: str
    allowed_accounts: set[str] = Field(min_length=1)
    code_mode_host: Path
    executor_codex: str
    logs: Path
    history_target: str | None = None
    history_token_file: Path | None = None
    gateway_target: str | None = None
    gateway_token_file: Path | None = None
    direct_executor_url: str | None = None
    max_live_sessions: int = Field(gt=0)
    host_rss_bytes: int = Field(gt=0)
    host_cgroup_root: Path | None = None
    host_pids: int = Field(default=64, gt=0)
    host_cpu_quota_us: int = Field(default=100000, gt=0)
    turn_timeout_seconds: int = Field(gt=0)
    rpc_timeout_seconds: int = Field(gt=0)
    lease_seconds: int = Field(gt=30)
    auto_compact_tokens: int | None = Field(default=None, gt=0)
