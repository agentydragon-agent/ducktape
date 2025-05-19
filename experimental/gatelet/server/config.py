"""Configuration management for Gatelet server.

TODO: Add configuration options for test database connections.
This will support running tests with a real database instead of mocks.
"""

import logging
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Literal, Union, Type, TypeVar, cast

import toml
from pydantic import BaseModel, Field, PostgresDsn, validator

logger = logging.getLogger(__name__)


class NoAuth(BaseModel):
    """No authentication configuration."""

    type: Literal["none"] = "none"


class BearerAuth(BaseModel):
    """Bearer token authentication configuration."""

    type: Literal["bearer"] = "bearer"
    token: str

    @validator("token")
    def token_not_empty(cls, v):
        if not v:
            raise ValueError("Token must not be empty")
        return v


WebhookAuthConfig = Union[NoAuth, BearerAuth]


class DatabaseSettings(BaseModel):
    dsn: PostgresDsn = Field(
        default="postgresql://postgres:postgres@localhost:5432/gatelet"
    )


class ServerSettings(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    log_level: str = Field(default="INFO")


class KeyInUrlAuthSettings(BaseModel):
    enabled: bool = Field(default=False)
    key_valid_days: int = Field(default=365)

    @property
    def key_validity(self) -> timedelta:
        """Get key validity period as timedelta."""
        return timedelta(days=self.key_valid_days)


class ChallengeResponseAuthSettings(BaseModel):
    enabled: bool = Field(default=False)
    num_options: int = Field(default=16)
    session_extension_seconds: int = Field(default=300)  # 5 minutes
    session_max_duration_seconds: int = Field(default=3600)  # 1 hour
    nonce_validity_seconds: int = Field(default=300)  # 5 minutes

    @property
    def session_extension(self) -> timedelta:
        """Get session extension period as timedelta."""
        return timedelta(seconds=self.session_extension_seconds)

    @property
    def session_max_duration(self) -> timedelta:
        """Get maximum session duration as timedelta."""
        return timedelta(seconds=self.session_max_duration_seconds)

    @property
    def nonce_validity(self) -> timedelta:
        """Get nonce validity period as timedelta."""
        return timedelta(seconds=self.nonce_validity_seconds)


class AuthSettings(BaseModel):
    key_in_url: KeyInUrlAuthSettings = Field(default=KeyInUrlAuthSettings())
    challenge_response: ChallengeResponseAuthSettings = Field(
        default=ChallengeResponseAuthSettings()
    )


class HomeAssistantSettings(BaseModel):
    api_url: str = Field(...)  # Required field
    api_token: str = Field(...)  # Required field
    entities: List[str] = Field(default_factory=list)


class WebhookIntegrationSettings(BaseModel):
    auth_config: WebhookAuthConfig = Field()
    enabled: bool = Field(default=False)


class WebhookSettings(BaseModel):
    integrations: Dict[str, WebhookIntegrationSettings] = Field(default_factory=dict)
    default_page_size: int = Field(default=10)

    @validator("integrations")
    def validate_integration_names(cls, v):
        for name in v.keys():
            # Check for URL-safe names
            if not re.match(r"^[a-zA-Z0-9_-]+$", name):
                raise ValueError(
                    f"Integration name '{name}' not only letters, numbers, underscores, and hyphens."
                )
            if len(name) > 50:
                raise ValueError(
                    f"Integration name '{name}' too long (max 50 characters)"
                )
        return v
        
    @validator("default_page_size")
    def validate_page_size(cls, v):
        if v < 1 or v > 100:
            raise ValueError("default_page_size must be between 1 and 100")
        return v


class Settings(BaseModel):
    database: DatabaseSettings
    server: ServerSettings
    auth: AuthSettings
    home_assistant: HomeAssistantSettings
    webhook: WebhookSettings

    @classmethod
    def from_file(cls, path: Path):
        """Load settings from file at path."""
        logger.info(f"Loading settings from {path.absolute()}")
        with open(path, "r") as f:
            config_dict = toml.load(f)
        return cls.parse_obj(config_dict)


# Load settings
settings = Settings.from_file(Path(os.getenv("GATELET_CONFIG", "gatelet.toml")))
