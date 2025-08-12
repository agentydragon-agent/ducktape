"""Thin CLI layer - just argument parsing and handler coordination."""

import asyncio
import inspect
import logging
import sys

import click
from colorama import init

from .client.handlers import (
    handle_copy_worktree,
    handle_create_worktree,
    handle_kill_daemon,
    handle_list_worktrees,
    handle_navigate_to_worktree,
    handle_path_command,
    handle_remove_worktree,
    handle_status,
    handle_status_single,
)
from .client.view_formatter import ViewFormatter
from .client.cd_utils import emit_cd_command
from .client.wt_client import WtClient
from .plugins import PluginIO, get_manager, resolve_command
from .shared.configuration import load_config
from .shared.constants import MAIN_REPO_ALIASES


def show_help() -> None:
    """Display help information with aligned columns."""
    click.echo("wt - Enhanced worktree management")
    click.echo()
    click.echo("USAGE:")
    click.echo("  wt [command] [args...]")
    click.echo()

    # Flags with dynamic padding
    flags = [
        ("--help", "Show this help"),
        ("--verbose", "Show client progress and daemon startup info"),
    ]
    max_flag = max(len(name) for name, _ in flags)
    click.echo("FLAGS:")
    for name, desc in flags:
        click.echo(f"  {name:<{max_flag}}  {desc}")
    click.echo()

    # Commands with dynamic padding
    commands = [
        ("wt", "Show status of all worktrees (includes GitHub PR status)"),
        ("wt <n>", "Navigate to worktree (or offer to create)"),
        ("wt status [name]", "Show detailed status"),
        ("wt ls", "List all worktrees"),
        ("wt -c <n>", "Create new worktree from main branch"),
        ("wt cp <src> <dst>", "Copy worktree (with dirty state)"),
        ("wt cp <n>", "Copy current worktree to new name"),
        ("wt rm <n>", "Remove worktree (with safety checks)"),
        ("wt path [name] [/path]", "Resolve worktree paths"),
        ("wt main", "Navigate to main repo"),
        ("wt kill-daemon", "Kill the wt daemon"),
        ("wt help", "Show this help"),
    ]
    max_cmd = max(len(cmd) for cmd, _ in commands)
    click.echo("COMMANDS:")
    for cmd, desc in commands:
        click.echo(f"  {cmd:<{max_cmd}}  {desc}")
    click.echo()

    # Examples (left as simple lines, not a table)
    examples = [
        ("wt", "Show all worktrees with PR status"),
        ("wt feature-branch", "Navigate to feature-branch worktree"),
        ("wt -c new-feature", "Create new worktree for new-feature"),
        ("wt cp experiment", "Copy current worktree to 'experiment'"),
        ("wt rm old-branch", "Remove old-branch worktree"),
    ]
    max_ex = max(len(cmd) for cmd, _ in examples)
    click.echo("EXAMPLES:")
    for cmd, desc in examples:
        click.echo(f"  {cmd:<{max_ex}}  # {desc}")


@click.group(
    invoke_without_command=True,
    context_settings={"ignore_unknown_options": True, "help_option_names": []},
)
@click.option("-h", "--help", is_flag=True, help="Show this help and exit")
@click.option("--verbose", is_flag=True, help="Show client progress and daemon startup info")
@click.pass_context
def main(ctx, help, verbose):
    """Main CLI entry point."""
    init()  # colorama

    if help:
        show_help()
        ctx.exit(0)

    # Accept --verbose anywhere (even after args like 'status')
    effective_verbose = bool(verbose) or ("--verbose" in (ctx.args or []))

    # Stash verbose in context for later
    ctx.obj = ctx.obj or {}
    ctx.obj["verbose"] = effective_verbose

    if ctx.invoked_subcommand is None:
        asyncio.run(_async_main(verbose=effective_verbose))
        return


def _create_cli_dependencies(verbose: bool = False):
    """Create common CLI dependencies."""
    config = load_config()
    formatter = ViewFormatter()
    # Route verbose flag into logging: show INFO logs when verbose, else WARNING
    logging_level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=logging_level)
    daemon_client = WtClient(config, verbose=verbose)
    plugin_manager = get_manager(config)
    return config, formatter, daemon_client, plugin_manager


async def _async_main(verbose: bool = False):
    """Async main function."""
    config, formatter, daemon_client, plugin_manager = _create_cli_dependencies(verbose=verbose)
    await handle_status(daemon_client, formatter)


@main.command(
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
        "help_option_names": [],
    },
)
@click.argument("args", nargs=-1)
@click.pass_context
def sh(ctx, args):
    """Handle shell integration with argument parsing."""
    # Combine args from Click with any extra args
    all_args = list(args) + ctx.args

    # Parse flags and commands
    filtered_args = []

    # Process arguments to extract flags
    for arg in all_args:
        if arg in {"--help", "-h"}:
            show_help()
            return
        if arg in ["-c", "--force"]:
            filtered_args.append(arg)
        elif arg.startswith("-"):
            continue
        else:
            filtered_args.append(arg)

    verbose = bool((ctx.obj or {}).get("verbose", False))
    config, formatter, daemon_client, plugin_manager = _create_cli_dependencies(verbose=verbose)

    # Run async command handler
    asyncio.run(
        _async_sh_main(
            daemon_client,
            formatter,
            config,
            plugin_manager,
            filtered_args,
            ctx,
        ),
    )


async def _async_sh_main(
    daemon_client,
    formatter,
    config,
    plugin_manager,
    filtered_args,
    ctx,
):
    """Async version of sh command handler."""
    # Route to appropriate handlers
    if not filtered_args:
        await handle_status(daemon_client, formatter)
        return

    cmd, *remaining_args = filtered_args

    # Plugin subcommand dispatch: wt <plugin> <args>
    plugin_callable = resolve_command(plugin_manager, cmd)
    if plugin_callable:
        io = PluginIO()
        result = plugin_callable(remaining_args, daemon_client, config, io)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, int):
            sys.exit(result)
        return

    # Handle special worktree names
    if cmd in MAIN_REPO_ALIASES:
        click.echo(f"Navigating to main repo ({cmd})")
        emit_cd_command(config.main_repo, main_repo=config.main_repo)
        return

    # Handle commands - pure argument parsing, delegate to handlers
    if cmd == "ls":
        await handle_list_worktrees(daemon_client, formatter)

    elif cmd == "rm":
        if not remaining_args:
            click.echo("Error: rm requires a worktree name")
            ctx.exit(1)
        force = "--force" in remaining_args
        name = next(arg for arg in remaining_args if arg != "--force")
        await handle_remove_worktree(config, name, force)

    elif cmd == "cp":
        if len(remaining_args) == 1:
            await handle_copy_worktree(config, remaining_args[0])
        elif len(remaining_args) == 2:
            await handle_copy_worktree(config, remaining_args[0], remaining_args[1])
        else:
            click.echo("Error: cp requires 1 or 2 arguments")
            ctx.exit(1)

    elif cmd == "-c":
        if not remaining_args:
            click.echo("Error: -c requires a worktree name")
            ctx.exit(1)
        await handle_create_worktree(config, remaining_args[0])

    elif cmd == "path":
        worktree_name = remaining_args[0] if remaining_args else None
        subpath = remaining_args[1] if len(remaining_args) > 1 else None
        await handle_path_command(config, worktree_name, subpath)

    elif cmd == "status":
        if remaining_args:
            await handle_status_single(daemon_client, formatter, remaining_args[0])
        else:
            await handle_status(daemon_client, formatter)

    elif cmd == "help":
        show_help()

    elif cmd == "kill-daemon":
        await handle_kill_daemon(config)

    else:
        # Default case: wt <x> - navigate to worktree
        await handle_navigate_to_worktree(config, cmd)


if __name__ == "__main__":
    main()
