"""Sidecar protocol for extending RunningInfrastructure."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adgn.agent.runtime.running import RunningInfrastructure


class Sidecar(ABC):
    """A plugin that attaches to RunningInfrastructure.

    Sidecars add optional functionality (UI, chat, loop, runtime exec)
    without being tightly coupled to the core infrastructure.

    Each sidecar is responsible for:
    - Mounting its MCP servers into the compositor during attach()
    - Cleaning up resources during detach()
    """

    @abstractmethod
    async def attach(self, running: RunningInfrastructure) -> None:
        """Attach this sidecar to running infrastructure.

        This method should mount any MCP servers into running.compositor
        and perform any other initialization needed.
        """

    async def detach(self) -> None:
        """Cleanup when infrastructure is closing (optional override)."""
