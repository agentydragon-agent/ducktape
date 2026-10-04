"""Workload-facing LLM ingress metadata contract."""

from pydantic import BaseModel, ConfigDict, Field


class ModelContextWindow(BaseModel):
    """An explicitly configured harness override, not a claim about maximum model capacity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1, description="Exposed model route id.")
    context_window_tokens: int = Field(gt=0, strict=True, description="Configured harness context window in tokens.")
