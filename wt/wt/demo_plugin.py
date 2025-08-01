from __future__ import annotations

from .plugins import PluginIO


def wt_commands() -> dict[str, object]:
    return {"demo": run}


def wt_init(config) -> None:
    return None


async def run(args: list[str], client, config, io: PluginIO) -> int:
    if args and args[0] == "cd-main":
        io.emit(f"cd {config.main_repo_resolved}")
        return 0
    if args and args[0] == "error-demo":
        io.controlled_error("demo controlled error", ["echo recovered"])  # exits 2
    # Default: show status via server
    resp = await client.get_status()
    count = len(resp.results)
    print(f"demo: {count} worktrees")
    return 0
