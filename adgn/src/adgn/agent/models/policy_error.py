from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PolicyErrorStage(StrEnum):
    READ = "read"
    PARSE = "parse"
    TESTS = "tests"


class PolicyError(BaseModel):
    stage: PolicyErrorStage = Field(description="Processing stage where error occurred")
    index: int | None = Field(None, description="Character index where error occurred in source text")
    length: int | None = Field(None, description="Length of error span in characters")
    message: str | None = Field(None, description="Human-readable error message")

    model_config = ConfigDict(extra="forbid")


class PolicyTestsSummary(BaseModel):
    ok: bool
    message: str | None = None
    error: PolicyError | None = None
    model_config = ConfigDict(extra="forbid")
