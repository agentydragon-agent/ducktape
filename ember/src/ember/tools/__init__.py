from __future__ import annotations

from typing import Callable

from ..tool_execution import ToolSpec
from .run_shell_command import build_spec as build_run_shell_command_spec
from .yield_control import build_spec as build_yield_control_spec


def build_tool_specs(on_yield: Callable[[], None]) -> dict[str, ToolSpec]:
    specs = [
        build_run_shell_command_spec(),
        build_yield_control_spec(on_yield),
    ]
    return {spec.name: spec for spec in specs}
