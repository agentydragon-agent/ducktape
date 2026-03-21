"""Result types for Twenty Questions eval runs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Correct(BaseModel):
    kind: Literal["correct"] = "correct"
    turns: int


class Timeout(BaseModel):
    kind: Literal["timeout"] = "timeout"
    limit: int


Result = Annotated[Correct | Timeout, Field(discriminator="kind")]


class LogEntry(BaseModel):
    timestamp: datetime
    player: Literal["guesser", "simulator"]
    model: str | None = None
    content: str
    tool_calls: list[dict[str, object]] = Field(default_factory=list)


class RunSummary(BaseModel):
    eval_name: str
    framework: str
    model: str
    api: str
    turns: int
    result: Result
