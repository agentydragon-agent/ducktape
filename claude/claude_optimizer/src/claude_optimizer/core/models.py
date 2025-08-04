from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator
from claude_code_sdk import Message


class FileInfo(BaseModel):
    path: str
    content: str


class SeedTask(BaseModel):
    id: str
    prompt: str
    description: str | None = None
    docker_image: str | None = None
    allowed_tools: list[str] | None = None
    pre_task_commands: str | None = None


class Criterion(BaseModel):
    name: str
    description: str


class ScoreWithRationale(BaseModel):
    score: float
    rationale: str


class CodeResult(BaseModel):
    task: str
    task_id: str
    agent_id: int
    timestamp: datetime
    messages: list[Message]
    files: list[FileInfo]
    
    class Config:
        arbitrary_types_allowed = True


class Grade(BaseModel):
    task: str
    task_id: str
    agent_id: int
    axes: dict[str, ScoreWithRationale]
    timestamp: datetime

    @property
    def overall_score(self) -> float:
        return self.axes["overall"].score

    @property
    def overall_rationale(self) -> str:
        return self.axes["overall"].rationale

    @model_validator(mode="after")
    def _ensure_overall_axis(self):
        assert "overall" in self.axes
        return self


class GradedCode(BaseModel):
    code_result: CodeResult
    grade: Grade
