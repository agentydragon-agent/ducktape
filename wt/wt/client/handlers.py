"""Pure handler functions for CLI commands."""


async def handle_status(daemon_client, formatter) -> None:
    """Handle the default status display command."""
    # Get all worktree status from daemon (empty list = all worktrees)
    all_status = await daemon_client.get_status([])

    if not all_status:
        import click

        click.echo("🤷 No worktrees found")
        return

    # Sort worktree items for display
    from ..shared.constants import MAIN_WORKTREE_DISPLAY_NAME

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
            import click as _click

            _click.echo("; ".join(msgs))


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
        import click

        click.echo(f"❌ No status available for '{worktree_name}'")
        return

    formatter.render_worktree_status_single(worktree_name, status, status.pr_info)


async def handle_create_worktree(config, name: str, from_default: bool = True) -> None:
    """Handle worktree creation."""
    try:
        import click

        click.echo(f"Creating worktree at: {config.worktrees_dir_resolved / name}")
        from .worktree_utils import create_worktree, emit_cd_command

        new_path = await create_worktree(config, name, from_default=from_default)
        emit_cd_command(new_path, config)
    except RuntimeError as e:
        import click

        click.echo(f"Error: {e}", err=True)
        import sys

        sys.exit(1)


async def handle_remove_worktree(config, name: str, force: bool = False) -> None:
    """Handle worktree removal."""
    import click

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
        from .worktree_utils import remove_worktree

        await remove_worktree(config, name, force=force)
        click.echo(f"✅ Successfully removed worktree '{name}'")

    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        import sys

        sys.exit(1)


async def handle_copy_worktree(config, source: str, dest: str | None = None) -> None:
    """Handle worktree copying."""
    import sys

    import click

    try:
        if dest is None:
            # wt cp <x> - create new worktree from current location
            new_name = source
            from .worktree_utils import get_current_worktree_info

            current_wt, _ = get_current_worktree_info(config)
            if not current_wt:
                click.echo("Error: Not in a worktree")
                sys.exit(1)

            click.echo(
                f"Creating worktree at: {config.worktrees_dir_resolved / new_name}",
            )
            from .worktree_utils import create_worktree, emit_cd_command

            new_path = await create_worktree(
                config,
                new_name,
                source_worktree=current_wt,
                from_default=False,
            )
            emit_cd_command(new_path, config)
        else:
            # wt cp <x> <y> - copy worktree x to new worktree y
            source_name, target_name = source, dest
            from .worktree_utils import (
                create_worktree,
                emit_cd_command,
                require_worktree_exists,
            )

            source_path = require_worktree_exists(config, source_name)

            click.echo(
                f"Creating worktree at: {config.worktrees_dir_resolved / target_name}",
            )
            new_path = await create_worktree(
                config,
                target_name,
                source_worktree=source_path,
                from_default=False,
            )
            emit_cd_command(new_path, config)

    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def handle_path_command(
    config,
    worktree_name: str | None = None,
    subpath: str | None = None,
) -> None:
    """Handle path resolution command."""
    import sys

    import click

    try:
        if worktree_name is None and subpath is None:
            # wt path - current worktree root
            from .worktree_utils import get_current_worktree_info

            current_wt, _ = get_current_worktree_info(config)
            if current_wt:
                click.echo(str(current_wt))
            else:
                click.echo("Error: Not in a worktree")
                sys.exit(1)
        elif subpath is None:
            # Single argument - could be worktree name or path spec
            arg = worktree_name
            if arg and arg.startswith(("/", "./")):
                # wt path /foo or wt path ./foo - path in current worktree
                from .worktree_utils import resolve_path

                path = resolve_path(config, None, arg or "")
                click.echo(str(path))
            else:
                # wt path <worktree> - root of specified worktree
                from .worktree_utils import require_worktree_exists

                wt_path = require_worktree_exists(config, arg or "")
                click.echo(str(wt_path))
        else:
            # wt path <worktree> /foo or wt path <worktree> ./foo
            from .worktree_utils import resolve_path

            path = resolve_path(config, worktree_name, subpath)
            click.echo(str(path))

    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


async def handle_navigate_to_worktree(config, worktree_name: str) -> None:
    """Handle navigation to worktree (with creation if needed)."""
    import sys

    import click

    from ..shared.constants import RESERVED_NAMES
    from .shell_utils import controlled_error

    if worktree_name in RESERVED_NAMES:
        click.echo(f"Error: '{worktree_name}' is a reserved name")
        sys.exit(1)

    from .worktree_utils import get_worktree_path

    wt_path = get_worktree_path(config, worktree_name)
    if wt_path.exists():
        # Teleport to existing worktree
        from .worktree_utils import emit_cd_command

        emit_cd_command(wt_path, config)
    elif click.confirm(
        f"Worktree '{worktree_name}' does not exist. Create it?",
        default=False,
    ):
        try:
            click.echo(f"Creating worktree at: {wt_path}")
            from .worktree_utils import create_worktree, emit_cd_command

            new_path = await create_worktree(config, worktree_name, from_default=True)
            emit_cd_command(new_path, config)
        except RuntimeError as e:
            click.echo(f"Error: {e}")
            sys.exit(1)
    else:
        controlled_error("Worktree creation cancelled")


async def handle_kill_daemon(config) -> None:
    """Handle kill-daemon command to stop the wt daemon."""

    import click

    pid_file = config.daemon_pid_file
    socket_file = config.daemon_socket_file

    if not pid_file.exists():
        click.echo("No daemon PID file found - daemon is not running")
        return

    try:
        with open(pid_file) as f:
            pid_str = f.read().strip()

        if not pid_str:
            click.echo("Empty PID file - cleaning up stale files")
            _cleanup_daemon_files(pid_file, socket_file)
            return

        pid = int(pid_str)

        # Check if process exists and kill it
        import psutil

        if psutil.pid_exists(pid):
            import os
            import signal

            click.echo(f"Killing wt daemon (PID {pid})...")

            try:
                os.kill(pid, signal.SIGTERM)

                # Wait a moment for graceful shutdown
                import time

                time.sleep(0.5)

                # If still running, force kill
                if psutil.pid_exists(pid):
                    click.echo("Daemon didn't respond to SIGTERM, sending SIGKILL...")
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.2)

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

    import click

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
