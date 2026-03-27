import datetime
import json
import sys
from pathlib import Path

import click
import platformdirs
from pydantic import ValidationError

from x.claude_linter.models import HookRequest, LinterHookResponse


def get_cache_dir() -> Path:
    """Get the cache directory for claude-linter.

    Uses platformdirs to respect XDG_CACHE_HOME on Linux.
    """
    return Path(platformdirs.user_cache_dir("claude-linter"))


def evaluate_pre(req: HookRequest) -> LinterHookResponse:
    return LinterHookResponse()


def evaluate_post(req: HookRequest) -> LinterHookResponse:
    return LinterHookResponse()


@click.group()
@click.version_option()
def cli() -> None:
    """Claude Linter CLI."""


# Hook commands have been removed - use claude-linter-v2 instead


@cli.command("clean")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
@click.option("--older-than", type=int, default=7, help="Delete logs older than N days (default: 7)")
def clean(dry_run: bool, older_than: int) -> None:
    """Clean up old log files."""
    log_dir = get_cache_dir()
    if not log_dir.exists():
        click.echo("No log directory found")
        return

    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=older_than)
    deleted_count = 0
    total_size = 0

    # Clean both hook-*.json and debug-*.log files
    for pattern in ["hook-*.json", "debug-*.log"]:
        for log_file in log_dir.glob(pattern):
            # Extract timestamp from filename
            try:
                # Format: {type}-{iso_timestamp}.{ext}
                timestamp_str = log_file.stem.split("-", 1)[1]
                file_time = datetime.datetime.fromisoformat(timestamp_str)

                if file_time < cutoff_date:
                    size = log_file.stat().st_size
                    total_size += size

                    if dry_run:
                        click.echo(f"Would delete: {log_file.name} ({size} bytes)")
                    else:
                        log_file.unlink()

                    deleted_count += 1
            except (IndexError, ValueError):
                # Skip files with unexpected format
                continue

    if dry_run:
        click.echo(f"\nWould delete {deleted_count} files ({total_size} bytes)")
    else:
        click.echo(f"Deleted {deleted_count} files ({total_size} bytes)")


@cli.command("hook")
def unified_hook() -> None:
    """Unified hook command that routes based on hook_event_name in JSON input."""
    # Create log directory
    log_dir = get_cache_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    # Read input
    input_json = sys.stdin.read()

    # Try to parse JSON for logging and routing
    try:
        input_data = json.loads(input_json)
    except json.JSONDecodeError:
        click.echo("Error: Invalid JSON input", err=True)
        sys.exit(1)

    # Parse request to get hook event name
    try:
        req = HookRequest.model_validate_json(input_json)
    except (ValidationError, json.JSONDecodeError) as e:
        click.echo(f"Error parsing hook request: {e}", err=True)
        sys.exit(1)

    # Route based on hook_event_name
    if not req.hook_event_name:
        click.echo("Error: hook_event_name not provided", err=True)
        sys.exit(1)

    # Create event-specific log file
    hook_type = req.hook_event_name.lower().replace("tooluse", "")  # "pre" or "post"
    log_file = log_dir / f"hook-{hook_type}-{datetime.datetime.now().isoformat()}.json"

    # Log input
    log_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "hook_type": hook_type,
        "hook_event_name": req.hook_event_name,
        "input": input_data,
    }

    # Route to appropriate handler
    if req.hook_event_name == "PreToolUse":
        decision = evaluate_pre(req)
    elif req.hook_event_name == "PostToolUse":
        decision = evaluate_post(req)
    else:
        # For other events (Notification, Stop, SubagentStop), return empty response
        decision = LinterHookResponse()

    # Handle output
    output_json = decision.model_dump_json(by_alias=True, exclude_none=True)
    print(output_json, file=sys.stdout)
    log_data["output"] = json.loads(output_json)

    # Log exit code
    log_data["exit_code"] = 0
    with Path(log_file).open("w") as f:
        json.dump(log_data, f, indent=2)

    sys.exit(0)
