from __future__ import annotations

from functools import singledispatch
from typing import Any

from pydantic import BaseModel
from rich.json import JSON
from rich.pretty import Pretty

# TODO(mpokorny): Consider wiring MiniCodex event-display into this layer as well.
# - Provide a bridge adapter to surface event-stream pretty-printing (ConsoleEventRenderer)
#   as Rich renderables when desired
# - Optionally unify final-output and event-stream rendering under a shared entrypoint
# - Keep data-model rendering decoupled; return Rich renderables only (no side effects)


@singledispatch
def render_to_rich(obj: Any):
    """Default Rich renderer.

    - Pydantic BaseModel → JSON.from_data(model_dump())
    - dict/list → JSON.from_data(obj)
    - Fallback → Pretty(obj)
    """
    return Pretty(obj)


@render_to_rich.register
def _render_pydantic(obj: BaseModel):
    return JSON.from_data(obj.model_dump())


@render_to_rich.register
def _render_dict(obj: dict):
    return JSON.from_data(obj)


@render_to_rich.register
def _render_list(obj: list):
    return JSON.from_data(obj)
