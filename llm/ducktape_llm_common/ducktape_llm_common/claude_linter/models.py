from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HookResponse(BaseModel):
    decision: Literal["approve", "block"] | None = None
    reason: str | None = None
    continue_: bool = Field(True, alias="continue")
    stopReason: str | None = None
    suppressOutput: bool = Field(False)

    model_config = ConfigDict(
        populate_by_name=True, alias_generator=None, use_enum_values=True, arbitrary_types_allowed=True
    )


class ToolInput(BaseModel):
    file_path: str
    content: str | None = None
    old_string: str | None = None
    new_string: str | None = None


class HookRequest(BaseModel):
    tool_name: str
    tool_input: ToolInput
    tool_response: dict | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)
