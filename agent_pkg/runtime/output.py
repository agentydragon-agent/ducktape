"""Output formatting utilities for agent init scripts.

Provides structured output helpers for printing workspace content, running
commands, and processing documentation files with Mako template rendering.
"""

import importlib.resources
import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from mako.template import Template

from mako_utils.preprocessor import markdown_heading_preprocessor

# Default workspace path in containers
WORKSPACE = Path("/workspace")


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"=== {title} ===")


def run_command(cmd: str | list[str | os.PathLike[str]], *, shell: bool = False) -> None:
    """Run a command and print output wrapped in <output> tags.

    Args:
        cmd: Command to run (string for shell=True, list for shell=False).
             List elements can be strings or Path objects.
        shell: Whether to run as shell command.

    Raises:
        subprocess.CalledProcessError: If the command fails (check=True).
    """
    if isinstance(cmd, list):
        cmd_strs: str | list[str] = [str(c) for c in cmd]
        cmd_str = " ".join(cmd_strs)
    else:
        cmd_strs = cmd
        cmd_str = cmd
    print(f'<output command="{cmd_str}">')
    subprocess.run(cmd_strs, shell=shell, check=True)
    print("</output>")


def run_command_template(cmd: str) -> str:
    """Execute command and return annotated output block.

    For use as Mako template helper: ${run_command("psql -c '...'")}
    """
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
    return f'<output command="{cmd}">\n{result.stdout}</output>'


def describe_relation_template(relation_name: str) -> str:
    r"""Return psql \d+ output for a table or view.

    DRY helper for schema documentation: ${describe_relation("reported_issues")}
    """
    return run_command_template(f'psql -c "\\d+ {relation_name}"')


def _make_template_context(helpers: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create Mako template context with standard helpers.

    Available in all templates:
    - workspace_dir — default workspace path
    - run_command(cmd) — execute shell command
    - describe_relation(name) — psql \\d+ output for tables/views
    - include_doc(pkg/path) — include and render from package resources
    - include_file(path) — include and render from filesystem
    """
    ctx: dict[str, Any] = {}
    ctx["workspace_dir"] = str(WORKSPACE)
    ctx["run_command"] = run_command_template
    ctx["describe_relation"] = describe_relation_template

    def include_doc(pkg_path: str, *, raw: bool = False) -> str:
        """Include doc from package resources, rendering Mako syntax."""
        pkg, _, p = pkg_path.partition("/")
        content = (importlib.resources.files(pkg) / p).read_text()
        if raw:
            return f'<doc source="{pkg_path}">\n{content}\n</doc>'
        rendered = Template(content, preprocessor=markdown_heading_preprocessor).render(**ctx)
        return f'<doc source="{pkg_path}">\n{rendered}\n</doc>'

    def include_file(file_path: str, *, raw: bool = False) -> str:
        """Include file from filesystem, rendering Mako syntax."""
        content = Path(file_path).read_text()
        if raw:
            return f'<doc source="{file_path}">\n{content}\n</doc>'
        rendered = Template(content, preprocessor=markdown_heading_preprocessor).render(**ctx)
        return f'<doc source="{file_path}">\n{rendered}\n</doc>'

    ctx["include_doc"] = include_doc
    ctx["include_file"] = include_file

    if helpers:
        ctx.update(helpers)

    return ctx


def render_doc(content: str, helpers: Mapping[str, Any] | None = None) -> str:
    """Render doc content with Mako, providing run_command and custom helpers."""
    all_helpers: dict[str, Callable[..., Any]] = {"run_command": run_command_template}
    if helpers:
        all_helpers.update(helpers)
    template = Template(content, preprocessor=markdown_heading_preprocessor)
    result: str = template.render(**all_helpers)
    return result


def render_and_print_file(path: str | Path, helpers: Mapping[str, Callable[..., Any]] | None = None) -> None:
    """Render a file with Mako and print it.

    Supports include_doc for including package docs from filesystem-based agent docs.
    """
    if isinstance(path, str):
        path = Path(path)
    content = path.read_text()

    ctx = _make_template_context(helpers)
    template = Template(content, preprocessor=markdown_heading_preprocessor)
    rendered = template.render(**ctx)
    print(f'<file path="{path}">')
    print(rendered)
    print("</file>")


def print_file(path: Path | str, title: str | None = None, workspace: Path = WORKSPACE) -> None:
    """Print a file wrapped in <file> tags."""
    if isinstance(path, str):
        path = Path(path)
    if not path.is_absolute():
        path = workspace / path

    if title:
        print_section(title)
    print(f'<file path="{path}">')
    print(path.read_text())
    print("</file>")


def print_workspace_tree(workspace: Path = WORKSPACE, depth: int = 3) -> None:
    """Print tree of the workspace to show available files."""
    print_section("Workspace Contents")
    run_command(["tree", "-L", str(depth), "-a", "-p", "--noreport", str(workspace)])


def render_agent_prompt(template_path: str, helpers: Mapping[str, Any] | None = None) -> None:
    """Render agent prompt from package resource.

    Supports:
    - ${include_doc("package/path")} — include doc with source annotation
    - ${include_file("/path")} — include from filesystem
    - ${describe_relation("name")} — psql \\d+ output for tables/views
    - ${run_command("cmd")} — shell command output
    """
    package, _, pkg_path = template_path.partition("/")
    resource = importlib.resources.files(package) / pkg_path
    root_content = resource.read_text()

    ctx = _make_template_context(helpers)
    template = Template(root_content, preprocessor=markdown_heading_preprocessor)
    print(template.render(**ctx))
