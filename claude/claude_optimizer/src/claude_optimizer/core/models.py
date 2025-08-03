from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator


class FileInfo(BaseModel):
    path: str
    content: str


class SeedTask(BaseModel):
    id: str
    prompt: str
    docker_image: str | None = None
    allowed_tools: list[str] | None = None
    pre_task_commands: str | None = None


class Criterion(BaseModel):
    name: str
    description: str
    evaluation_criteria: str


class ScoreWithRationale(BaseModel):
    score: float
    rationale: str


class CodeResult(BaseModel):
    task: str
    task_id: str
    agent_id: int
    timestamp: datetime
    messages: list[dict[str, Any]]
    files: list[FileInfo]


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


class GradedCode(BaseModel):
    code_result: CodeResult
    grade: Grade
