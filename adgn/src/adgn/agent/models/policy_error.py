from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PolicyErrorCode(StrEnum):
    READ_ERROR = "read_error"
    PARSE_ERROR = "parse_error"


class PolicyError(BaseModel):
    stage: Literal["read", "parse", "tests"]
    code: PolicyErrorCode
    index: int | None = None
    length: int | None = None
    message: str | None = None

    model_config = ConfigDict(extra="forbid")


class PolicyTestsSummary(BaseModel):
    ok: bool
    message: str | None = None
    error: PolicyError | None = None
    model_config = ConfigDict(extra="forbid")
