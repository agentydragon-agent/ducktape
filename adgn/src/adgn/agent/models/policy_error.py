from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PolicyErrorCode(StrEnum):
    READ_ERROR = "read_error"
    PARSE_ERROR = "parse_error"


class PolicyError(BaseModel):
    stage: Literal["read", "parse", "tests"] = Field(description="Processing stage where error occurred")
    code: PolicyErrorCode = Field(description="Error code (read_error, parse_error)")
    index: int | None = Field(None, description="Character/token index where error occurred")
    length: int | None = Field(None, description="Length of error span in characters/tokens")
    message: str | None = Field(None, description="Human-readable error message")

    model_config = ConfigDict(extra="forbid")


class PolicyTestsSummary(BaseModel):
    ok: bool
    message: str | None = None
    error: PolicyError | None = None
    model_config = ConfigDict(extra="forbid")
