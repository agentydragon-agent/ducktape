"""Discriminated union of all Claude Code hook inputs.

Parsed once in hook_dispatch.py, then isinstance/match dispatches to the
appropriate handler. Uses hook_event_name as the Pydantic discriminator.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Discriminator

from devinfra.claude.claude_api.hook_input import HookInput as SessionStartInput
from devinfra.claude.claude_api.post_tool_use import PostToolUseInput
from devinfra.claude.claude_api.pre_tool_use import PreToolUseInput

AnyHookInput = Annotated[SessionStartInput | PreToolUseInput | PostToolUseInput, Discriminator("hook_event_name")]
