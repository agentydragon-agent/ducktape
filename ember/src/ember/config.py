from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from openai.types.responses import ResponseIncludable
from openai.types.shared.reasoning_effort import ReasoningEffort
from pydantic import BaseModel, ConfigDict, ValidationError

from .system_prompt import load_system_prompt


class MatrixSettings(BaseModel):
    """Matrix configuration for the pilot."""

    base_url: str | None
    access_token: str | None
    admin_user_id: str | None = None
    control_rooms_path: Path
    model_config = ConfigDict(frozen=True, extra="forbid")

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.access_token)


class OpenAISettings(BaseModel):
    api_key: str
    model: str
    system_prompt: str
    reasoning_effort: ReasoningEffort = "medium"
    include_encrypted_reasoning: bool = True
    model_config = ConfigDict(frozen=True, extra="forbid")

    @property
    def include(self) -> list[ResponseIncludable]:
        includes: list[ResponseIncludable] = []
        if self.include_encrypted_reasoning:
            includes.append(cast(ResponseIncludable, "reasoning.encrypted_content"))
        return includes


class PilotSettings(BaseModel):
    matrix: MatrixSettings
    openai: OpenAISettings
    history_path: Path
    state_dir: Path
    model_config = ConfigDict(frozen=True, extra="forbid")


def load_settings() -> PilotSettings:
    """Load pilot settings from environment variables."""

    if not (api_key := os.getenv("OPENAI_API_KEY")):
        raise RuntimeError("OPENAI_API_KEY must be set for the pilot")

    state_dir = Path(os.getenv("PILOT_STATE_DIR", "/var/lib/ember")).expanduser()
    history_path = state_dir / "pilot_history.jsonl"

    try:
        return PilotSettings(
            matrix=MatrixSettings(
                base_url=os.getenv("MATRIX_BASE_URL"),
                access_token=os.getenv("MATRIX_ACCESS_TOKEN"),
                admin_user_id=os.getenv("MATRIX_ADMIN_USER_ID"),
                control_rooms_path=state_dir / "control_rooms.json",
            ),
            openai=OpenAISettings(
                api_key=api_key,
                model=os.getenv("OPENAI_MODEL", "gpt-5"),
                system_prompt=load_system_prompt(),
                reasoning_effort=cast(
                    ReasoningEffort, os.getenv("OPENAI_REASONING_EFFORT", "medium")
                ),
                include_encrypted_reasoning=_env_flag("OPENAI_INCLUDE_ENCRYPTED_REASONING", default=True),
            ),
            history_path=history_path,
            state_dir=state_dir,
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
