"""Shared functionality for init scripts.

All agents call print_bootstrap() which prints:
1. Workspace tree (file structure)
2. All documentation files from /workspace/docs/
3. Environment variables

Individual agents can then print additional context (helper functions, CLI docs, etc.).
"""

import os
from pathlib import Path
import subprocess

from sqlalchemy import text

from adgn.props.agent_helpers import get_current_agent_run
from adgn.props.db import get_session

WORKSPACE = Path("/workspace")


def print_section(title: str) -> None:
    print(f"=== {title} ===")


def run_command(cmd: str | list[str], *, shell: bool = False) -> None:
    """Run a command and print output wrapped in <output> tags.

    Args:
        cmd: Command to run (string for shell=True, list for shell=False).
        shell: Whether to run as shell command.

    Crashes if the command fails (check=True).
    """
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    print(f'<output command="{cmd_str}">')
    subprocess.run(cmd, shell=shell, check=True)
    print("</output>")


def print_file(path: Path | str, title: str | None = None) -> None:
    """Print a workspace file wrapped in <file> tags.

    Args:
        path: Path to the file (absolute or relative to WORKSPACE).
        title: Optional section title to print before the file.
    """
    if isinstance(path, str):
        path = Path(path)
    if not path.is_absolute():
        path = WORKSPACE / path

    if title:
        print_section(title)
    print(f'<file path="{path}">')
    print(path.read_text())
    print("</file>")


def print_workspace_tree() -> None:
    """Print tree of the workspace to show what files are available.

    Uses the `tree` command with common options:
    - -L 3: limit depth to 3 levels
    - -a: show hidden files
    - -p: show file permissions (so executable scripts are visible)
    - --noreport: skip the summary line

    Crashes if tree fails (check=True) - init should fail fast on missing tools.
    """
    print_section("Workspace Contents")
    run_command(["tree", "-L", "3", "-a", "-p", "--noreport", str(WORKSPACE)])


def _print_doc_file(md_file: Path) -> None:
    """Print a single doc file with executable line expansion."""
    rel_path = md_file.relative_to(WORKSPACE)
    print(f'<file path="/workspace/{rel_path}">')
    content = md_file.read_text()
    for line in content.splitlines():
        if line.startswith("!"):
            cmd = line[1:]  # Strip the !
            run_command(cmd, shell=True)
        else:
            print(line)
    print("</file>")


def print_docs(order: list[str], skip: list[str] | None = None) -> None:
    """Print documentation files from the workspace docs directory.

    Args:
        order: Explicit ordering of doc files (relative to docs/, e.g., ["postgres_access.md", "db/critiques.md"]).
               Files are printed in this order. Must cover all files (minus skip).
        skip: Files to skip (relative to docs/).

    Executable lines: Lines starting with `!` are executed as shell commands and
    their output replaces the line. This enables live schema output via `!psql`.

    Fail-fast: Crashes if docs/ doesn't exist or if order doesn't cover all files.
    """
    docs_dir = WORKSPACE / "docs"

    # Discover all .md files
    all_md_files = set(docs_dir.rglob("*.md"))
    if not all_md_files:
        raise FileNotFoundError(f"No .md files found in {docs_dir}")

    skip_set = {docs_dir / s for s in (skip or [])}

    # Validate ordering covers everything
    ordered_files = [docs_dir / f for f in order]
    expected = all_md_files - skip_set
    ordered_set = set(ordered_files)

    missing = expected - ordered_set
    if missing:
        missing_rel = [str(f.relative_to(docs_dir)) for f in missing]
        raise ValueError(f"order missing files: {missing_rel}")

    extra = ordered_set - expected
    if extra:
        extra_rel = [str(f.relative_to(docs_dir)) for f in extra]
        raise ValueError(f"order contains non-existent or skipped files: {extra_rel}")

    # Print in specified order
    for md_file in ordered_files:
        _print_doc_file(md_file)


def print_env_info(agent_name: str) -> None:
    """Print environment variables for agent."""
    print_section(f"{agent_name} Agent Environment")
    print(f"PGHOST: {os.environ.get('PGHOST', '(not set)')}")
    print(f"PGUSER: {os.environ.get('PGUSER', '(not set)')}")
    print(f"PGDATABASE: {os.environ.get('PGDATABASE', '(not set)')}")
    print(f"MCP_SERVER_URL: {os.environ.get('MCP_SERVER_URL', '(not set)')}")


def verify_db_access() -> None:
    """Verify database access and RLS context."""
    print_section("Database Access Verification")

    with get_session() as session:
        result = session.execute(text("SELECT current_user")).scalar()
        agent_run_id = session.execute(text("SELECT current_agent_run_id()")).scalar()
        if not agent_run_id:
            raise RuntimeError("current_agent_run_id() returned NULL - RLS will block writes")
        print(f"✓ Connected as {result}")


def print_definition_helpers() -> None:
    """Print the definition helper functions source code.

    For agents that create other agent definitions (prompt_optimizer, improvement).
    Expects the helpers to be present at /workspace/definition_helpers.py.
    Raises FileNotFoundError if missing (hard error - definition is misconfigured).
    """
    print_file("definition_helpers.py", title="Definition Helper Functions")


def print_bootstrap(agent_name: str, docs_order: list[str], docs_skip: list[str] | None = None) -> None:
    """Print standard bootstrap context for all agents.

    This is the main entry point for init scripts. It prints:
    1. Workspace tree (file structure)
    2. All documentation files from /workspace/docs/
    3. Environment variables

    Args:
        agent_name: Name of the agent (e.g., "Critic", "Grader")
        docs_order: Explicit ordering of doc files (relative to docs/).
        docs_skip: Files to skip (relative to docs/).
    """
    print_workspace_tree()
    print_docs(docs_order, docs_skip)
    print_env_info(agent_name)


def print_agent_config() -> object:
    """Print agent configuration as JSON and return the type_config.

    Fetches the current agent run from the session and prints its type_config.

    Returns:
        The type_config Pydantic model for further use if needed.
    """
    with get_session() as session:
        agent_run = get_current_agent_run(session)
        print("\n=== AGENT CONFIGURATION ===")
        print(agent_run.type_config.model_dump_json(indent=2))
        return agent_run.type_config
