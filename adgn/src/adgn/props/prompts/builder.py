from __future__ import annotations

from adgn.props.critic.models import CriticSubmitPayload, ReportedIssue
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.grader.models import OccurrenceMatch, OccurrenceResult
from adgn.props.models.true_positive import LineRange, Occurrence

from .schemas import build_input_schemas_json
from .util import render_prompt_template


def build_enforce_prompt(
    scope_text: str,
    *,
    compositor: PropertiesDockerCompositor,
    schemas_json: dict[str, dict],
    supplemental_text: str | None = None,
) -> str:
    return render_prompt_template(
        "prompts/enforce.j2.md",
        scope_text=scope_text,
        supplemental_text=supplemental_text,
        working_dir=compositor.working_dir,
        definitions_container_dir=compositor.definitions_container_dir,
        schemas_json=schemas_json,
    )


def build_grade_from_json_prompt(*, submit_tool_name: str, compositor: PropertiesDockerCompositor) -> str:
    """Compose grader prompt that reads ground truth from MCP resources."""
    # Import inside function to avoid circular dependency (grader.py imports from this module)
    from adgn.props.grader.grader import (
        GRADER_CANONICAL_TPS_RESOURCE_URI,
        GRADER_CRITIQUE_ISSUES_RESOURCE_URI,
        GRADER_KNOWN_FPS_RESOURCE_URI,
    )

    schemas_json = build_input_schemas_json(
        [Occurrence, LineRange, ReportedIssue, CriticSubmitPayload, OccurrenceResult, OccurrenceMatch]
    )

    return render_prompt_template(
        "prompts/grade_from_json.j2.md",
        canonical_tps_resource_uri=GRADER_CANONICAL_TPS_RESOURCE_URI,
        critique_issues_resource_uri=GRADER_CRITIQUE_ISSUES_RESOURCE_URI,
        known_fps_resource_uri=GRADER_KNOWN_FPS_RESOURCE_URI,
        submit_tool_name=submit_tool_name,
        working_dir=compositor.working_dir,
        definitions_container_dir=compositor.definitions_container_dir,
        schemas_json=schemas_json,
    )
