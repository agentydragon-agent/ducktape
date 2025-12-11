from __future__ import annotations

from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from typing import Any

from compact_json import Formatter  # type: ignore[import-untyped]
from jinja2 import Environment, PackageLoader

from adgn.props.critic.models import ReportedIssue
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.grader.models import GradeMetrics, GradeSubmitInput
from adgn.props.models.true_positive import LineRange, Occurrence
from adgn.props.prompts.schemas import build_input_schemas_json


def _load_mcp_http_instructions() -> str:
    """Load MCP HTTP connection instructions from markdown file.

    Generic instructions for agents running in Docker containers that need to connect
    to an MCP server on the host via HTTP transport.
    Based on design doc: src/adgn/props/docs/plans/mcp_over_docker_network.md
    """
    prompts_pkg = files("adgn.props.prompts")
    md_file = prompts_pkg / "mcp_http_connection.md"
    return md_file.read_text()


MCP_HTTP_CONNECTION_INSTRUCTIONS = _load_mcp_http_instructions()


def _compact_json_filter(value: Any, max_width: int = 100) -> str:
    """Jinja2 filter for compact JSON formatting using compact_json.

    Args:
        value: Python object to serialize (usually dict from model_json_schema())
        max_width: Maximum line width before wrapping (default: 100)

    Returns:
        Compact JSON string with smart line wrapping
    """
    formatter = Formatter(max_inline_length=max_width)
    return formatter.serialize(value)  # type: ignore[no-any-return]


def get_templates_env() -> Environment:
    """Load prompt templates from the installed package using importlib.resources.

    Templates are rooted at adgn.props package directory.
    Callers specify paths relative to adgn/props/ (e.g., "prompts/foo.j2.md", "critic/prompts/bar.j2.md").
    """
    env = Environment(
        loader=PackageLoader("adgn", "props"),
        autoescape=False,  # Prompts are text for LLMs, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Register custom filters
    env.filters["compactjson"] = _compact_json_filter
    return env


def render_prompt_template(name: str, **ctx: object) -> str:
    env = get_templates_env()
    tmpl = env.get_template(name)
    return str(tmpl.render(**ctx)).strip()


def enumerate_files_from_path(root: Path) -> list[Path]:
    """Enumerate all regular files in a directory tree (relative paths).

    Args:
        root: Directory to walk

    Returns:
        List of relative Path objects for all regular files found

    Example:
        files = enumerate_files_from_path(Path("/some/project"))
        scope_text = build_scope_text(files)
    """
    files = []
    for item in root.rglob("*"):
        if item.is_file():
            try:
                files.append(item.relative_to(root))
            except ValueError:
                # Skip files that can't be made relative (shouldn't happen with rglob)
                continue
    return files


def build_scope_text(files: Iterable[Path]) -> str:
    """Generate explicit file list for prompt headers.

    Args:
        files: Iterable of Path objects (typically SnapshotRelativePath from all_discovered_files.keys())

    Returns:
        Formatted string with bullet list of files, e.g.:
        "Review the following files:
        - src/foo.py
        - src/bar.py"

    Example:
        # For specimens
        scope_text = build_scope_text(hydrated.all_discovered_files.keys())

        # For local paths
        files = enumerate_files_from_path(Path("/project"))
        scope_text = build_scope_text(files)
    """
    file_list = "\n".join(f"- {file}" for file in sorted(files, key=str))
    return f"Review the following files:\n{file_list}"


def build_standard_context(
    *,
    files: Iterable[Path],
    compositor: PropertiesDockerCompositor,
    supplemental_text: str | None = None,
    include_schemas: bool = True,
) -> dict[str, object]:
    """Build standard Jinja context for properties prompts.

    Args:
        files: Iterable of Path objects (file list for scope)
        compositor: PropertiesDockerCompositor with Docker configuration
        supplemental_text: Optional additional context (e.g., specimen notes)
        include_schemas: Whether to include schemas_json (default: True)

    Returns:
        Dictionary suitable for Jinja template.render(**context)
    """
    context: dict[str, object] = {
        "files": sorted(files, key=str),
        "working_dir": compositor.working_dir,
        "definitions_container_dir": compositor.definitions_container_dir,
        "supplemental_text": supplemental_text,
        "read_only": True,
        "include_reporting": False,
    }

    if include_schemas:
        context["schemas_json"] = build_input_schemas_json(
            [Occurrence, LineRange, ReportedIssue, GradeMetrics, GradeSubmitInput]
        )

    return context
