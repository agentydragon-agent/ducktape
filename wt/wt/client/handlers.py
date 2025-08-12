"""Pure handler functions for CLI commands."""

import asyncio
import os
import signal
import sys
from pathlib import Path

import click
import psutil

from ..shared.constants import MAIN_WORKTREE_DISPLAY_NAME, RESERVED_NAMES
from ..shared.protocol import TeleportCdThere
from .worktree_utils import (
    emit_cd_command,
    get_current_worktree_info,
    remove_worktree,
)
from .wt_client import WtClient


async def handle_status(daemon_client, formatter) -> None:
    """Handle the default status display command."""
    # Get all worktree status from daemon (empty list = all worktrees)
    all_status = await daemon_client.get_status([])

    if not all_status:
        click.echo("🤷 No worktrees found")
        return

    # Sort worktree items for display

    def sort_key(item):
        name, status = item
        # Always prioritize the main worktree
        if name == MAIN_WORKTREE_DISPLAY_NAME:
            return (0, "main")  # main worktree always first
        return (1, name)  # others alphabetically

    sorted_items = sorted(
        all_status.results.items(),
        key=lambda x: sort_key((x[1].name, x[1])),
    )
    display_items = [(result.name, result) for wtid, result in sorted_items]

    formatter.render_top_status_bar(all_status)
    formatter.render_worktree_status_all(display_items)

    components = all_status.components
    if components:
        msgs = []
        if (
            components.github
            and components.github.state
            and components.github.state.value != "ok"
        ):
            last_err = components.github.last_error or ""
            msgs.append(f"github: {last_err}".strip())
        if components.gitstatusd and components.gitstatusd.metrics:
            total = int(components.gitstatusd.metrics.get("total", 0))
            running = int(components.gitstatusd.metrics.get("running", 0))
            if running < total:
                msgs.append(f"gitstatusd {running}/{total}")
        if msgs:
            click.echo("; ".join(msgs))


async def handle_list_worktrees(daemon_client, formatter) -> None:
    """Handle the ls command to list all worktrees."""
    # For now, delegate to status since we need the daemon for worktree discovery
    # This could be enhanced later if needed
    await handle_status(daemon_client, formatter)


async def handle_status_single(daemon_client, formatter, worktree_name: str) -> None:
    """Handle status command for a single worktree."""
    # Get all status and find the specific worktree
    all_status = await daemon_client.get_status([])

    # Find the worktree by name in the results
    status = None
    for result in all_status.results.values():
        if result.name == worktree_name:
            status = result
            break

    if not status:
        click.echo(f"❌ No status available for '{worktree_name}'")
        return

    formatter.render_worktree_status_single(worktree_name, status, status.pr_info)


async def handle_create_worktree(config, name: str, from_default: bool = True) -> None:
    """Handle worktree creation."""
    try:
        daemon_client = WtClient(config)
        new_path = await daemon_client.create_worktree_convenience(name, from_default=from_default)
        emit_cd_command(new_path, config)
    except RuntimeError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


async def handle_remove_worktree(config, name: str, force: bool = False) -> None:
    """Handle worktree removal."""
    try:
        click.echo(f"🔍 Checking worktree '{name}' for removal...")

        # Ask for confirmation unless forced
        if not force:
            worktree_path = config.worktrees_dir_resolved / name
            click.echo(
                f"⚠️  About to permanently remove worktree '{name}' at {worktree_path}",
            )
            if not click.confirm("Are you sure you want to continue?", default=False):
                click.echo("Removal cancelled.")
                return

        click.echo(f"🗑️  Removing worktree '{name}'...")
        await remove_worktree(config, name, force=force)
        click.echo(f"✅ Successfully removed worktree '{name}'")

    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


async def handle_copy_worktree(config, source: str, dest: str | None = None) -> None:
    """Handle worktree copying."""
    try:
        if dest is None:
            # wt cp <x> - create new worktree from current location
            new_name = source
            current_wt, _ = get_current_worktree_info(config)
            if not current_wt:
                click.echo("Error: Not in a worktree")
                sys.exit(1)

            daemon_client = WtClient(config)
            new_path = await daemon_client.create_worktree_convenience(
                new_name,
                source_name=current_wt.name if current_wt is not None else new_name,
                from_default=False,
            )
            emit_cd_command(new_path, config)
        else:
            # wt cp <x> <y> - copy worktree x to new worktree y
            source_name, target_name = source, dest

            daemon_client = WtClient(config)
            _ = await daemon_client.require_worktree_exists(source_name)
            new_path = await daemon_client.create_worktree_convenience(
                target_name,
                source_name=source_name,
                from_default=False,
            )
            emit_cd_command(new_path, config)

    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


async def handle_path_command(
    config,
    worktree_name: str | None = None,
    subpath: str | None = None,
) -> None:
    client = WtClient(config)
    if worktree_name is None and subpath is None:
        p = await client.resolve_path_simple(None, "/")
        click.echo(str(p))
    elif subpath is None:
        arg = worktree_name or ""
        if arg.startswith(("/", "./")):
            p = await client.resolve_path_simple(None, arg)
            click.echo(str(p))
        else:
            p = await client.require_worktree_exists(arg)
            click.echo(str(p))
    else:
        p = await client.resolve_path_simple(worktree_name, subpath)
        click.echo(str(p))


async def handle_navigate_to_worktree(config, worktree_name: str) -> None:
    """Handle navigation to worktree (with creation if needed)."""
    if worktree_name in RESERVED_NAMES:
        click.echo(f"Error: '{worktree_name}' is a reserved name")
        sys.exit(1)

    daemon_client = WtClient(config)

    info = await daemon_client.get_worktree_by_name(worktree_name)

    if info.exists and info.absolute_path:
        emit_cd_command(Path(info.absolute_path), config)
        return

    tt = await daemon_client.teleport_target(worktree_name, str(Path.cwd()))
    if isinstance(tt, TeleportCdThere):
        emit_cd_command(Path(tt.cd_path), config)
        return

    if click.confirm(f"Worktree '{worktree_name}' does not exist. Create it?", default=False):
        try:
            new_path = await daemon_client.create_worktree_convenience(worktree_name, from_default=True)
            emit_cd_command(new_path, config)
        except RuntimeError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
    else:
        click.echo("Cancelled.")


async def handle_kill_daemon(config) -> None:
    """Handle kill-daemon command to stop the wt daemon."""

    pid_file = config.daemon_pid_file
    socket_file = config.daemon_socket_file

    if not pid_file.exists():
        click.echo("No daemon PID file found - daemon is not running")
        return

    try:
        pid_str = pid_file.read_text().strip()

        if not pid_str:
            click.echo("Empty PID file - cleaning up stale files")
            _cleanup_daemon_files(pid_file, socket_file)
            return

        pid = int(pid_str)

        # Check if process exists and kill it
        if psutil.pid_exists(pid):
            click.echo(f"Killing wt daemon (PID {pid})...")

            try:
                os.kill(pid, signal.SIGTERM)

                # Wait a moment for graceful shutdown
                await asyncio.sleep(0.5)

                # If still running, force kill
                if psutil.pid_exists(pid):
                    click.echo("Daemon didn't respond to SIGTERM, sending SIGKILL...")
                    os.kill(pid, signal.SIGKILL)
                    await asyncio.sleep(0.2)

                if psutil.pid_exists(pid):
                    click.echo(f"Warning: Process {pid} is still running", err=True)
                else:
                    click.echo("✓ Daemon stopped successfully")

            except (ProcessLookupError, PermissionError) as e:
                click.echo(f"Failed to kill daemon: {e}", err=True)

        else:
            click.echo("Daemon process not found - cleaning up stale files")

        # Clean up daemon files
        _cleanup_daemon_files(pid_file, socket_file)

    except (ValueError, OSError, ImportError) as e:
        click.echo(f"Error reading PID file: {e}", err=True)
        _cleanup_daemon_files(pid_file, socket_file)


def _cleanup_daemon_files(pid_file, socket_file) -> None:
    """Clean up daemon PID and socket files."""

    try:
        if pid_file.exists():
            pid_file.unlink()
            click.echo("✓ Cleaned up PID file")
    except OSError as e:
        click.echo(f"Warning: Could not remove PID file: {e}", err=True)

    try:
        if socket_file.exists():
            socket_file.unlink()
            click.echo("✓ Cleaned up socket file")
    except OSError as e:
        click.echo(f"Warning: Could not remove socket file: {e}", err=True)
