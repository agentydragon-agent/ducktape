#!/usr/bin/env python3
from __future__ import annotations

from typing import Annotated, Any, Literal

from anthropic.types.tool_param import ToolParam
from openai.types.responses import ResponseCreateParams
from pydantic import BaseModel, Field

from adgn.llm.anthropic.types import AnthropicMessage

# ------------------------
# Crush (OpenAI Responses)
# ------------------------


class ToolFunction(BaseModel):
    type: Literal["function"] = "function"
    name: str
    description: str | None = None
    # Responses uses input_schema; Chat uses parameters
    input_schema: dict[str, Any] | None = None
    strict: bool | None = None


class CrushWirelogMeta(BaseModel):
    event_type: str | None = None
    path: str | None = None


class CrushSample(BaseModel):
    kind: Literal["crush"] = "crush"
    correlation_id: str | None = None
    timestamp: int | None = None
    oai_request: ResponseCreateParams
    wirelog: CrushWirelogMeta | None = None


# ------------------------
# CCR (Anthropic-style via SDK)
# ------------------------


class CCRRequest(BaseModel):
    """CCR request using Pydantic-validated Anthropic message types.

    Uses adgn.anthropic_utils types (Pydantic BaseModels) instead of
    anthropic.types TypedDicts for stronger typing and runtime validation.
    """

    system: str | None = None
    messages: list[AnthropicMessage]
    tools: list[ToolParam] | None = None


class CCRSample(BaseModel):
    kind: Literal["ccr"] = "ccr"
    correlation_id: str | None = None
    timestamp: int | None = None
    anthropic_request: CCRRequest


# ------------------------
# Eval pipeline IO records
# ------------------------


class EvalSampleRecord(BaseModel):
    request: dict[str, Any]
    response: dict[str, Any]
    new_assistant_message: dict[str, Any]
    correlation_id: str | None = None
    timestamp: int | None = None
    anthropic_request: CCRRequest | None = None
    grade: dict[str, Any] | None = None


class EvalGradeRecord(BaseModel):
    request: dict[str, Any]
    response: dict[str, Any]
    correlation_id: str | None = None
    timestamp: int | None = None


# Discriminated union for dataset samples
Sample = Annotated[CCRSample | CrushSample, Field(discriminator="kind")]
