"""Shared spans for concurrent VM scenarios and their fixture lifetimes."""

from collections.abc import Coroutine
from typing import Any

from opentelemetry import trace

tracer = trace.get_tracer(__name__)


async def traced_vm_scenario(name: str, scenario: Coroutine[Any, Any, None]) -> None:
    with tracer.start_as_current_span("vm.scenario", attributes={"scenario": name}):
        await scenario
