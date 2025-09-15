#!/usr/bin/env python3
from __future__ import annotations
from typing import Annotated, Any, Literal
from openai.types.responses import ResponseCreateParams
from pydantic import BaseModel, Field


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
    system: str | list[dict[str, Any]] | None = None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None


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
