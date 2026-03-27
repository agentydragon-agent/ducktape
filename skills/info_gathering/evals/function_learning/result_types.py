"""Result types for the function learning eval."""

from typing import Literal

from pydantic import BaseModel, Field

from skills.info_gathering.evals.harness import RunSummary as _BaseRunSummary


class ProgramError(BaseModel):
    input: str
    error: str


class TurnResult(BaseModel):
    turn: int
    query: str
    query_result: str
    hamming_loss: int
    errors: list[ProgramError] = Field(default_factory=list)


class FunctionLearningResult(BaseModel):
    kind: Literal["completed"] = "completed"
    total_hamming_loss: int
    per_turn_losses: list[int]


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class RunSummary(_BaseRunSummary[FunctionLearningResult]):
    function_name: str
    n_bits: int
    m_bits: int
    usage: TokenUsage = Field(default_factory=TokenUsage)
