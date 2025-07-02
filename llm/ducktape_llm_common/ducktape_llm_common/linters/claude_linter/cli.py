import json
import os
import sys

import click

from .config import get_merged_config
from .precommit_runner import PreCommitRunner
from .registry import run_additional_checks


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
    run_additional_checks(paths)
    sys.exit(0)


@cli.command("hook")
def hook():
    """Run as configured Claude Code hook (reads JSON from stdin)."""
    data = json.load(sys.stdin)
    tool = data.get("tool_name")
    if tool != "Write":
        sys.exit(0)
    params = data.get("tool_input", {})
    file_path = params.get("file_path")
    if not file_path:
        sys.exit(0)
    paths = [file_path]
    config = get_merged_config(paths)
    runner = PreCommitRunner(config)
    runner.run(paths, hook_mode=True)
    sys.exit(0)
