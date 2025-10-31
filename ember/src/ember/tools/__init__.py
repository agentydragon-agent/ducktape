from __future__ import annotations

from typing import Callable

from ..config import SleepUntilUserMessagePolicy
from ..tool_execution import ToolSpec
from .run_shell_command import build_spec as build_run_shell_command_spec
from .sleep_until_user_message import (
    ConversationStatusProvider,
    build_spec as build_sleep_until_user_message_spec,
)


def build_tool_specs(
    on_sleep: Callable[[], None],
    status_provider: ConversationStatusProvider,
    policy: SleepUntilUserMessagePolicy,
) -> dict[str, ToolSpec]:
    specs = [
        build_run_shell_command_spec(),
        build_sleep_until_user_message_spec(on_sleep, status_provider, policy),
    ]
    return {spec.name: spec for spec in specs}
