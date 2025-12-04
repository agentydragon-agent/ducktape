from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader

from adgn.props.critic.models import CriticSubmitPayload, ReportedIssue
from adgn.props.grader.models import GradeMetrics, GradeSubmitInput
from adgn.props.models.true_positive import IssueCore, LineRange, Occurrence
from adgn.props.prompts.schemas import build_input_schemas_json


def get_templates_env() -> Environment:
    """Load prompt templates from the installed package using importlib.resources.

    Templates live under the adgn.props.prompts package directory.
    """
    return Environment(
        loader=PackageLoader("adgn.props", "prompts"),
        autoescape=False,  # Prompts are text for LLMs, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
    )


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
        files: Iterable of Path objects (typically SpecimenRelativePath from all_discovered_files.keys())

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
    wiring: Any,  # PropertiesDockerWiring, avoid circular import
    available_tools: list[str] | None = None,
    supplemental_text: str | None = None,
    include_schemas: bool = True,
) -> dict[str, Any]:
    """Build standard Jinja context for properties prompts.

    Args:
        files: Iterable of Path objects (file list for scope)
        wiring: PropertiesDockerWiring with image/volumes/network config
        available_tools: List of tool names (default: [])
        supplemental_text: Optional additional context (e.g., specimen notes)
        include_schemas: Whether to include schemas_json (default: True)

    Returns:
        Dictionary suitable for Jinja template.render(**context)
    """
    context: dict[str, Any] = {
        "files": sorted(files, key=str),
        "wiring": wiring,
        "available_tools": available_tools if available_tools is not None else [],
        "supplemental_text": supplemental_text,
        "read_only": True,
        "include_tools": False,
        "include_reporting": False,
    }

    if include_schemas:
        context["schemas_json"] = build_input_schemas_json(
            [Occurrence, LineRange, IssueCore, ReportedIssue, CriticSubmitPayload, GradeMetrics, GradeSubmitInput]
        )

    return context
