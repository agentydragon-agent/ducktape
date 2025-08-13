from __future__ import annotations

import importlib.metadata as importlib_metadata
from collections.abc import Callable

import pluggy

from .client.shell_utils import controlled_error, emit_command

PROJECT_NAME = "wt"
ENTRYPOINT_GROUP = "wt.plugins"


class _Spec:
    @pluggy.HookspecMarker(PROJECT_NAME)
    def wt_commands(self) -> dict[str, Callable] | None:
        """
        Return mapping of subcommand name -> callable
        Signatures supported:
        - async def run(args: list[str], client, config, io) -> int | None
        - def run(args: list[str], client, config, io) -> int | None
        """

    @pluggy.HookspecMarker(PROJECT_NAME)
    def wt_init(self, config) -> None:
        """
        Optional initialization hook; can modify config or set globals.
        """


class _Impl:
    @pluggy.HookimplMarker(PROJECT_NAME)
    def wt_commands(self) -> dict[str, Callable]:  # type: ignore[override]
        return {}

    @pluggy.HookimplMarker(PROJECT_NAME)
    def wt_init(self, config) -> None:  # type: ignore[override]
        return None


class PluginIO:
    def emit(self, cmd: str) -> None:
        emit_command(cmd)

    def controlled_error(self, message: str, commands: list[str] | None = None) -> None:
        controlled_error(message, commands)


def get_manager(config) -> pluggy.PluginManager:
    pm = pluggy.PluginManager(PROJECT_NAME)
    pm.add_hookspecs(_Spec)
    pm.register(_Impl())

    eps = importlib_metadata.entry_points().select(group=ENTRYPOINT_GROUP)  # type: ignore[attr-defined]
    for ep in eps:
        # Only catch expected plugin loading errors; let programming errors crash
        try:
            pm.register(ep.load())
        except (ImportError, AttributeError):
            # Plugin is misconfigured or missing; skip
            continue

    pm.hook.wt_init(config=config)
    return pm


def get_plugin_commands(pm: pluggy.PluginManager) -> dict[str, Callable]:
    commands: dict[str, Callable] = {}
    for mapping in pm.hook.wt_commands():
        commands.update(mapping or {})
    return commands


def resolve_command(pm: pluggy.PluginManager, name: str):
    mapping = get_plugin_commands(pm)
    return mapping.get(name)
