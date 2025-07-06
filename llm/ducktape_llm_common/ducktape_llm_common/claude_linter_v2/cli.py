#!/usr/bin/env python3
"""
Claude Linter v2 - Main CLI entry point.

A unified code quality and permission management system for Claude Code.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import click

from . import __version__
from .hooks import HookHandler


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version=__version__)
def cli(ctx: click.Context) -> None:
    """Claude Linter v2 - Code quality and permission management for Claude Code."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.option(
    "--type",
    "hook_type",
    type=click.Choice(["pre", "post", "stop"]),
    required=True,
    help="Hook type to execute",
)
@click.option(
    "--request-json",
    type=str,
    help="JSON request from Claude Code (stdin if not provided)",
)
def hook(hook_type: str, request_json: Optional[str]) -> None:
    """Handle Claude Code hook requests."""
    # Read JSON from stdin if not provided
    if request_json is None:
        request_json = sys.stdin.read()
    
    try:
        request_data = json.loads(request_json)
    except json.JSONDecodeError as e:
        error_response = {
            "error": f"Invalid JSON: {e}",
            "continue": False,
        }
        click.echo(json.dumps(error_response))
        sys.exit(1)
    
    # Process hook
    handler = HookHandler()
    result = handler.handle(hook_type, request_data)
    
    # Output result
    click.echo(json.dumps(result))
    
    # Exit code based on decision
    if result.get("decision") == "block":
        sys.exit(2)
    sys.exit(0)


@cli.group()
def session() -> None:
    """Manage session-scoped permissions."""
    pass


@session.command("allow")
@click.argument("predicate")
@click.option("--expires", type=str, help="Duration (e.g., '2h', '30m')")
@click.option("--session", type=str, help="Specific session ID (default: all in current dir)")
@click.option("--dir", type=Path, help="Directory to affect (default: current)")
def session_allow(predicate: str, expires: Optional[str], session: Optional[str], dir: Optional[Path]) -> None:
    """Grant temporary permissions using Python predicates."""
    from .session import SessionManager
    
    manager = SessionManager()
    
    # Parse expiration
    expiry_time = None
    if expires:
        # TODO: Parse duration string to datetime
        pass
    
    # Add rule
    target_dir = dir or Path.cwd()
    affected = manager.add_rule(
        predicate=predicate,
        action="allow",
        expires=expiry_time,
        session_id=session,
        directory=target_dir,
    )
    
    if affected:
        click.echo(f"✓ Permission granted to {affected} session(s)")
        click.echo(f"  Predicate: {predicate}")
        if expires:
            click.echo(f"  Expires: {expires}")
    else:
        click.echo("⚠ No active sessions found in specified directory")


@session.command("deny")
@click.argument("predicate")
@click.option("--session", type=str, help="Specific session ID (default: all in current dir)")
@click.option("--dir", type=Path, help="Directory to affect (default: current)")
def session_deny(predicate: str, session: Optional[str], dir: Optional[Path]) -> None:
    """Deny permissions using Python predicates."""
    from .session import SessionManager
    
    manager = SessionManager()
    target_dir = dir or Path.cwd()
    
    affected = manager.add_rule(
        predicate=predicate,
        action="deny",
        expires=None,
        session_id=session,
        directory=target_dir,
    )
    
    if affected:
        click.echo(f"✓ Permission denied to {affected} session(s)")
        click.echo(f"  Predicate: {predicate}")
    else:
        click.echo("⚠ No active sessions found in specified directory")


@session.command("list")
@click.option("--all", is_flag=True, help="Show all sessions (not just current dir)")
def session_list(all: bool) -> None:
    """List active sessions and their permissions."""
    from .session import SessionManager
    
    manager = SessionManager()
    sessions = manager.list_sessions(all_dirs=all)
    
    if not sessions:
        click.echo("No active sessions found")
        return
    
    current_dir = Path.cwd()
    
    # Group by directory
    by_dir: Dict[Path, list] = {}
    for session_info in sessions:
        dir_path = session_info["directory"]
        if dir_path not in by_dir:
            by_dir[dir_path] = []
        by_dir[dir_path].append(session_info)
    
    # Display current directory first
    if current_dir in by_dir:
        click.echo(f"Sessions in {current_dir}:")
        for session_info in by_dir[current_dir]:
            _display_session(session_info)
        del by_dir[current_dir]
    
    # Display other directories
    if by_dir and all:
        click.echo("\nSessions in other directories:")
        for dir_path, sessions in sorted(by_dir.items()):
            click.echo(f"\n{dir_path}:")
            for session_info in sessions:
                _display_session(session_info)


def _display_session(session_info: Dict[str, Any]) -> None:
    """Display a single session's information."""
    session_id = session_info["id"]
    last_seen = session_info["last_seen"]
    
    # Calculate time ago
    now = datetime.now()
    delta = now - datetime.fromisoformat(last_seen)
    if delta.total_seconds() < 60:
        ago = f"{int(delta.total_seconds())}s ago"
    elif delta.total_seconds() < 3600:
        ago = f"{int(delta.total_seconds() / 60)}m ago"
    else:
        ago = f"{int(delta.total_seconds() / 3600)}h ago"
    
    click.echo(f"  {session_id[:8]}... - last seen {ago}")
    
    # Show active rules
    rules = session_info.get("rules", [])
    if rules:
        for rule in rules:
            action = "✓" if rule["action"] == "allow" else "✗"
            expires = f" (expires {rule['expires']})" if rule.get("expires") else ""
            click.echo(f"    {action} {rule['predicate']}{expires}")


@cli.group()
def profile() -> None:
    """Manage permission profiles."""
    pass


@profile.command("activate")
@click.argument("name")
@click.option("--session", type=str, help="Specific session ID (default: all in current dir)")
def profile_activate(name: str, session: Optional[str]) -> None:
    """Activate a predefined permission profile."""
    # TODO: Implement profile activation
    click.echo(f"Activating profile: {name}")


@profile.command("list")
def profile_list() -> None:
    """List available profiles."""
    # TODO: Load and display profiles from config
    click.echo("Available profiles:")
    click.echo("  refactoring - Edit Python files, run git and tests")
    click.echo("  debugging - Full read access, limited write")


@cli.command()
@click.argument("paths", nargs=-1, type=Path)
@click.option("--fix", is_flag=True, help="Auto-fix issues where possible")
@click.option("--categories", multiple=True, help="Categories to check/fix")
def check(paths: tuple[Path, ...], fix: bool, categories: tuple[str, ...]) -> None:
    """Check files for linting issues (direct usage)."""
    # TODO: Implement direct file checking
    if not paths:
        paths = (Path.cwd(),)
    
    click.echo(f"Checking {len(paths)} path(s)...")
    if fix:
        click.echo(f"Auto-fixing categories: {', '.join(categories) or 'all'}")


@cli.command()
@click.argument("paths", nargs=-1, type=Path, required=True)
@click.option("--categories", multiple=True, help="Categories to fix")
def fix(paths: tuple[Path, ...], categories: tuple[str, ...]) -> None:
    """Fix linting issues in files."""
    # Delegate to check with --fix
    ctx = click.get_current_context()
    ctx.invoke(check, paths=paths, fix=True, categories=categories)


if __name__ == "__main__":
    cli()