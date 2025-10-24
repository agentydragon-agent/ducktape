from __future__ import annotations

from typing import Callable

from pydantic import BaseModel, ConfigDict

from ..tool_execution import ToolPayload, ToolSpec


class YieldControlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class YieldControlResult(BaseModel):
    status: str = "waiting_for_matrix"
    model_config = ConfigDict(extra="forbid")


def build_spec(on_yield: Callable[[], None]) -> ToolSpec:
    async def handler(_: YieldControlArgs) -> ToolPayload:
        on_yield()
        return YieldControlResult()

    return ToolSpec(
        name="yield_control",
        description=(
            "Call when there is nothing to do. The runtime will resume once new Matrix messages arrive."
        ),
        handler=handler,
    )
