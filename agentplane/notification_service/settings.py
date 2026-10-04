"""YAML deployment configuration; GitHub secrets are supplied through Secret-backed environment variables."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

# gazelle:include_dep @pypi//pyyaml

CONFIG_FILE_ENV = "AGENTPLANE_NOTIFICATIONS_CONFIG_FILE"


class ActionsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    url: str = Field(description="Base URL of the Actions Service's canonical request/event read API.")
    token_file: Path = Field(
        description="Path to the projected ServiceAccount token for Actions; reread for each request to follow rotation."
    )


class GitHubSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    app_id: int = Field(gt=0, description="Public numeric GitHub App ID; not a secret.")
    private_key: SecretStr = Field(
        min_length=1,
        description="PEM App private key, supplied through a Secret-backed environment variable.",
    )
    webhook_secret: SecretStr = Field(
        min_length=32,
        description="Webhook HMAC signing secret, supplied through a Secret-backed environment variable.",
    )
    max_body_bytes: int = Field(
        default=1024 * 1024, ge=1024, le=25 * 1024 * 1024, description="Maximum raw webhook request body size in bytes."
    )
    webhook_concurrency: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Maximum concurrent webhook requests per replica, held through durable commit; saturation returns 503.",
    )
    reconciliation_seconds: int = Field(
        default=120,
        ge=0,
        le=3600,
        description=(
            "Grace period after receipt for CI events not yet correlated to a PR or branch head. "
            "Reconsider on new webhooks and once at expiry, then advance past unmatched events. "
            "Not a polling interval or a delay for events that already match; zero disables the grace period."
        ),
    )


class SandboxServiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    target: str = Field(description="Sandbox Service gRPC host:port for session access and runner commands.")
    token_file: Path = Field(
        description="Path to the rotating projected ServiceAccount token used to authenticate to Sandbox Service."
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTPLANE_NOTIFICATIONS_",
        env_nested_delimiter="__",
        extra="forbid",
        cli_parse_args=True,
        cli_kebab_case=True,
        hide_input_in_errors=True,
    )
    database_url: str = Field(description="PostgreSQL DSN supplied through a Secret-backed environment variable.")
    namespace: str = Field(description="Allowed caller ServiceAccount namespace and destination sandbox namespace.")
    actions: ActionsSettings
    sandbox_service: SandboxServiceSettings
    token_audience: str = Field(
        default="agentplane-egress",
        description=(
            "Audience required when TokenReview authenticates callers of this API. "
            "agentplane-egress is the shared first-party workload compatibility audience, "
            "not a notification routing setting; changing it requires coordinating caller token issuance."
        ),
    )
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    github: GitHubSettings | None = Field(
        default=None, description="GitHub source configuration. Omit or set to null to disable it."
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources = [init_settings, env_settings, dotenv_settings]
        if config_file := os.environ.get(CONFIG_FILE_ENV):
            if not Path(config_file).is_file():
                raise ValueError("configured notification settings file is not a regular file")
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=config_file))
        return (*sources, file_secret_settings)
