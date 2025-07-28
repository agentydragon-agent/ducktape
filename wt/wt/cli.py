"""Thin CLI layer - just argument parsing and handler coordination."""

import click
from colorama import init

from .client.daemon_client import WtClient
from .client.handlers import (
    handle_copy_worktree,
    handle_create_worktree,
    handle_list_worktrees,
    handle_navigate_to_worktree,
    handle_path_command,
    handle_remove_worktree,
    handle_status,
    handle_status_single,
)
from .client.view_formatter import ViewFormatter
from .shared.configuration import load_config
from .shared.constants import MAIN_REPO_ALIASES


def show_help() -> None:
    """Display help information."""
    click.echo("wt - Enhanced worktree management")
    click.echo()
    click.echo("USAGE:")
    click.echo("  wt [command] [args...]")
    click.echo()
    click.echo("FLAGS:")
    click.echo("  --help     Show this help")
    click.echo()
    click.echo("COMMANDS:")
    click.echo("  wt                    Show status of all worktrees (includes GitHub PR status)")
    click.echo("  wt <n>             Navigate to worktree (or offer to create)")
    click.echo("  wt status [name]      Show detailed status")
    click.echo("  wt ls                 List all worktrees")
    click.echo("  wt -c <n>          Create new worktree from main branch")
    click.echo("  wt cp <src> <dst>     Copy worktree (with dirty state)")
    click.echo("  wt cp <n>          Copy current worktree to new name")
    click.echo("  wt rm <n>          Remove worktree (with safety checks)")
    click.echo("  wt path [name] [/path] Resolve worktree paths")
    click.echo("  wt main               Navigate to main repo")
    click.echo("  wt kill-daemon        Kill the GitStatusd daemon")
    click.echo("  wt help               Show this help")
    click.echo()
    click.echo("EXAMPLES:")
    click.echo("  wt                    # Show all worktrees with PR status")
    click.echo("  wt feature-branch     # Navigate to feature-branch worktree")
    click.echo("  wt -c new-feature     # Create new worktree for new-feature")
    click.echo("  wt cp experiment      # Copy current worktree to 'experiment'")
    click.echo("  wt rm old-branch      # Remove old-branch worktree")


@click.group(
    invoke_without_command=True,
    context_settings={"ignore_unknown_options": True, "help_option_names": []},
)
@click.option("-h", "--help", is_flag=True, help="Show this help and exit")
@click.pass_context
def main(ctx, help):
    """Main CLI entry point."""
    init()  # colorama

    if help:
        show_help()
        ctx.exit(0)

    if ctx.invoked_subcommand is None:
        import asyncio
        asyncio.run(_async_main())


def _create_cli_dependencies():
    """Create common CLI dependencies."""
    config = load_config()
    formatter = ViewFormatter()
    daemon_client = WtClient(config)
    return config, formatter, daemon_client


async def _async_main():
    """Async main function."""
    config, formatter, daemon_client = _create_cli_dependencies()
    await handle_status(daemon_client, formatter)


@main.command(
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
        "help_option_names": [],
    }
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
        if arg == "--help" or arg == "-h":
            show_help()
            return
        elif arg in ["-c", "--force"]:
            filtered_args.append(arg)
        elif arg.startswith("-"):
            continue
        else:
            filtered_args.append(arg)

    config, formatter, daemon_client = _create_cli_dependencies()

    # Run async command handler
    import asyncio

    asyncio.run(_async_sh_main(daemon_client, formatter, config, filtered_args, ctx))


async def _async_sh_main(daemon_client, formatter, config, filtered_args, ctx):
    """Async version of sh command handler."""
    # Route to appropriate handlers
    if not filtered_args:
        await handle_status(daemon_client, formatter)
        return

    cmd, *remaining_args = filtered_args

    # Handle special worktree names
    if cmd in MAIN_REPO_ALIASES:
        click.echo(f"Navigating to main repo ({cmd})")
        return

    # Handle commands - pure argument parsing, delegate to handlers
    if cmd == "ls":
        await handle_list_worktrees(daemon_client, formatter)

    elif cmd == "rm":
        if not remaining_args:
            click.echo("Error: rm requires a worktree name")
            ctx.exit(1)
        force = "--force" in remaining_args
        name = [arg for arg in remaining_args if arg != "--force"][0]
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
        handle_path_command(config, worktree_name, subpath)

    elif cmd == "status":
        if remaining_args:
            await handle_status_single(daemon_client, formatter, remaining_args[0])
        else:
            await handle_status(daemon_client, formatter)

    elif cmd == "help":
        show_help()

    elif cmd == "kill-daemon":
        from .client.handlers import handle_kill_daemon

        await handle_kill_daemon(config)

    else:
        # Default case: wt <x> - navigate to worktree
        await handle_navigate_to_worktree(config, cmd)


if __name__ == "__main__":
    main()
