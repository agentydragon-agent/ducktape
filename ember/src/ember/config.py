from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from openai.types.responses import ResponseIncludable
from openai.types.shared.reasoning_effort import ReasoningEffort
from pydantic import BaseModel, ConfigDict, ValidationError

from .system_prompt import load_system_prompt
from .secrets import ProjectedSecret


class MatrixSettings(BaseModel):
    """Matrix configuration for the pilot."""

    base_url: str | None
    access_token_secret: ProjectedSecret
    admin_user_id: str | None = None
    state_store: Path
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.access_token_secret.value())


class OpenAISettings(BaseModel):
    api_key_secret: ProjectedSecret
    model: str
    system_prompt: str
    reasoning_effort: ReasoningEffort = "medium"
    include_encrypted_reasoning: bool = True
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    @property
    def include(self) -> list[ResponseIncludable]:
        includes: list[ResponseIncludable] = []
        if self.include_encrypted_reasoning:
            includes.append(cast(ResponseIncludable, "reasoning.encrypted_content"))
        return includes

    @property
    def api_key(self) -> str:
        value = self.api_key_secret.value(required=True)
        assert value is not None  # for type-checkers
        return value


class EmberSettings(BaseModel):
    matrix: MatrixSettings
    openai: OpenAISettings
    history_path: Path
    state_dir: Path
    workspace_path: Path
    model_config = ConfigDict(frozen=True, extra="forbid")


def load_settings() -> EmberSettings:
    """Load Ember settings from environment variables and mounted secrets."""

    state_dir = Path(os.getenv("PILOT_STATE_DIR", "/var/lib/ember")).expanduser()
    workspace_dir = os.getenv("EMBER_WORKSPACE_DIR")
    workspace_path = (Path(workspace_dir) if workspace_dir else state_dir / "workspace").expanduser()
    history_path = state_dir / "pilot_history.jsonl"

    matrix_access_token = ProjectedSecret(
        name="matrix_access_token",
        env_var="MATRIX_ACCESS_TOKEN",
    )
    openai_api_key = ProjectedSecret(
        name="openai_api_key",
        env_var="OPENAI_API_KEY",
    )

    try:
        return EmberSettings(
            matrix=MatrixSettings(
                base_url=os.getenv("MATRIX_BASE_URL"),
                access_token_secret=matrix_access_token,
                admin_user_id=os.getenv("MATRIX_ADMIN_USER_ID"),
                state_store=state_dir / "matrix_state.json",
            ),
            openai=OpenAISettings(
                api_key_secret=openai_api_key,
                model=os.getenv("OPENAI_MODEL", "gpt-5"),
                system_prompt=load_system_prompt(),
                reasoning_effort=cast(
                    ReasoningEffort, os.getenv("OPENAI_REASONING_EFFORT", "medium")
                ),
                include_encrypted_reasoning=_env_flag("OPENAI_INCLUDE_ENCRYPTED_REASONING", default=True),
            ),
            history_path=history_path,
            state_dir=state_dir,
            workspace_path=workspace_path,
        )
    except ValidationError as exc:  # pragma: no cover - configuration errors should surface loudly
        raise RuntimeError(f"Invalid pilot configuration: {exc}") from exc


def _env_flag(name: str, default: bool) -> bool:
    if (raw := os.getenv(name)) is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default
