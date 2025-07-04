import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

import click

from .config import get_merged_config
from .models import HookRequest, HookResponse
from .precommit_runner import PreCommitRunner


def evaluate_pre(req: HookRequest) -> tuple[HookResponse, int]:
    # Pre-write hook evaluation - early bailout
    if req.tool_name != "Write":
        # Return empty response to let normal permission flow continue
        return HookResponse(), 0

    inp = req.tool_input
    if not inp.file_path or inp.content is None:
        # Return empty response to let normal permission flow continue
        return HookResponse(), 0

    # Run hooks on temp file
    tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=Path(inp.file_path).suffix)
    tmp.write(inp.content)
    tmp_path = tmp.name
    tmp.close()

    try:
        # Get config for fixing
        config = get_merged_config([str(Path(inp.file_path).parent)], fix=True)
        runner = PreCommitRunner(config)

        # First run: with fixes to see if issues are fixable
        original_content = Path(tmp_path).read_text()
        ret1, out1, err1 = runner.run([tmp_path], cwd=str(Path(inp.file_path).parent))
        fixed_content = Path(tmp_path).read_text()

        # If content didn't change
        if original_content == fixed_content:
            if ret1 != 0:
                # Had violations but none were fixable
                return _block_with_reason(out1, err1), 0
            # No violations at all - let normal permission flow continue
            return HookResponse(reason="Pre-commit checks passed"), 0

        # Content changed, check if pre-commit is satisfied with the fixed version
        ret2, out2, err2 = runner.run([tmp_path], cwd=str(Path(inp.file_path).parent))
        fixed_again_content = Path(tmp_path).read_text()

        if fixed_content == fixed_again_content:
            # All violations were fixable - let normal permission flow continue
            return HookResponse(
                reason="Pre-commit checks passed (auto-fixable violations will be fixed after write)"
            ), 0
        else:
            # Pre-commit keeps changing things - non-fixable violations found
            return _block_with_reason(out2, err2), 0

    finally:
        Path(tmp_path).unlink()


def _block_with_reason(stdout: str, stderr: str) -> HookResponse:
    """Create a block response with formatted error output."""
    reason = f"Pre-write check failed with non-fixable errors:\nOutput:\n{stdout}\nError:\n{stderr}"
    return HookResponse(decision="block", reason=reason)


def evaluate_post(req: HookRequest) -> tuple[HookResponse, int]:
    # Post-write hook evaluation
    if req.tool_name not in ["Write", "Edit", "MultiEdit"]:
        return HookResponse(decision="approve"), 0
    file_path = req.tool_input.file_path
    if not file_path or not Path(file_path).exists():
        return HookResponse(decision="approve"), 0
    original = Path(file_path).read_text()
    config = get_merged_config([file_path], fix=True)
    runner = PreCommitRunner(config)
    ret, out, err = runner.run([file_path], cwd=str(Path(file_path).parent))
    new = Path(file_path).read_text()
    if new == original:
        return HookResponse(decision="approve"), 0
    return HookResponse(decision="block", reason="FYI: Auto-fixes were applied"), 0


@click.group()
@click.version_option()
def cli():
    """Claude Linter CLI."""
    pass


@cli.command("check")
@click.option("--files", "-f", multiple=True, type=click.Path(exists=True))
def check(files):
    """Run checks on given files or all in current directory."""
    paths = list(files) if files else [os.getcwd()]
    config = get_merged_config(paths)
    runner = PreCommitRunner(config)
    runner.run(paths)
    sys.exit(0)


@cli.group("hook")
def hook():
    """Run as configured Claude Code hook (reads JSON from stdin)."""
    pass


@hook.command("pre")
def pre_hook():
    """pre-write hook"""
    # Create log directory
    log_dir = Path.home() / ".cache" / "claude-linter"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"hook-pre-{datetime.datetime.now().isoformat()}.json"

    # Read input
    input_json = sys.stdin.read()

    # Try to parse JSON for logging
    try:
        input_data = json.loads(input_json)
    except json.JSONDecodeError:
        input_data = input_json  # Fall back to raw string if invalid JSON

    # Log input
    log_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "hook_type": "pre",
        "input": input_data,
    }

    try:
        req = HookRequest.model_validate_json(input_json)
    except Exception as e:
        # Log error
        log_data["error"] = str(e)
        log_data["output"] = None
        with open(log_file, "w") as f:
            json.dump(log_data, f, indent=2)
        click.echo("Error parsing JSON input", err=True)
        sys.exit(1)

    decision, code = evaluate_pre(req)
    output_json = decision.model_dump_json(by_alias=True, exclude_none=True)

    # Log output
    log_data["output"] = json.loads(output_json)  # Parse JSON to embed as structure
    log_data["exit_code"] = code
    with open(log_file, "w") as f:
        json.dump(log_data, f, indent=2)

    print(output_json, file=sys.stdout)
    sys.exit(code)


# Expose post-hook logic
@hook.command("post")
def post_hook():
    """post-write hook"""
    # Create log directory
    log_dir = Path.home() / ".cache" / "claude-linter"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"hook-post-{datetime.datetime.now().isoformat()}.json"

    # Read input
    input_json = sys.stdin.read()

    # Try to parse JSON for logging
    try:
        input_data = json.loads(input_json)
    except json.JSONDecodeError:
        input_data = input_json  # Fall back to raw string if invalid JSON

    # Log input
    log_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "hook_type": "post",
        "input": input_data,
    }

    try:
        req = HookRequest.model_validate_json(input_json)
    except Exception as e:
        # Log error
        log_data["error"] = str(e)
        log_data["output"] = None
        with open(log_file, "w") as f:
            json.dump(log_data, f, indent=2)
        click.echo("Error parsing JSON input", err=True)
        sys.exit(1)

    decision, code = evaluate_post(req)
    if decision:
        output_json = decision.model_dump_json(by_alias=True, exclude_none=True)
        print(output_json, file=sys.stdout)
        # Parse JSON to embed as structure
        log_data["output"] = json.loads(output_json)
    else:
        output_json = None
        log_data["output"] = None

    # Log exit code
    log_data["exit_code"] = code
    with open(log_file, "w") as f:
        json.dump(log_data, f, indent=2)

    sys.exit(code)


# Expose pre/post as top-level commands for compatibility with tests
cli.add_command(pre_hook, name="pre")
cli.add_command(post_hook, name="post")


@cli.command("clean")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
@click.option("--older-than", type=int, default=7, help="Delete logs older than N days (default: 7)")
def clean(dry_run: bool, older_than: int) -> None:
    """Clean up old log files."""
    log_dir = Path.home() / ".cache" / "claude-linter"
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
