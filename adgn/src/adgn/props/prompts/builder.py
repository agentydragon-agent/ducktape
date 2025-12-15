from __future__ import annotations

from pydantic import TypeAdapter

from adgn.props.critic.models import CriticSubmitPayload, ReportedIssue
from adgn.props.docker_env import PropertiesDockerCompositor
from adgn.props.grader.models import (
    CritiqueInputIssue,
    KnownFalsePositive,
    OccurrenceMatch,
    OccurrenceResult,
    TruePositiveIssue,
)
from adgn.props.models.true_positive import LineRange, Occurrence

from .schemas import build_input_schemas_json, compact_json_serialize
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


def build_grade_from_json_prompt(
    *,
    true_positive_issues: list[TruePositiveIssue],
    critique_issues: list[CritiqueInputIssue],
    known_fps: list[KnownFalsePositive],
    submit_tool_name: str,
    compositor: PropertiesDockerCompositor,
) -> str:
    """Compose grader prompt that consumes structured JSON and requires submit via grader_submit."""
    schemas_json = build_input_schemas_json(
        [Occurrence, LineRange, ReportedIssue, CriticSubmitPayload, OccurrenceResult, OccurrenceMatch]
    )

    # Serialize lists to compact JSON strings before template rendering
    # Note: The TruePositiveIssue model already includes occurrence_id field in occurrences
    canonical_json = compact_json_serialize(
        TypeAdapter(list[TruePositiveIssue]).dump_python(true_positive_issues, mode="json")
    )
    critique_json = compact_json_serialize(
        TypeAdapter(list[CritiqueInputIssue]).dump_python(critique_issues, mode="json")
    )
    known_fps_json = compact_json_serialize(TypeAdapter(list[KnownFalsePositive]).dump_python(known_fps, mode="json"))

    return render_prompt_template(
        "prompts/grade_from_json.j2.md",
        canonical_issues_json=canonical_json,
        critique_issues_json=critique_json,
        known_fps_json=known_fps_json,
        submit_tool_name=submit_tool_name,
        working_dir=compositor.working_dir,
        definitions_container_dir=compositor.definitions_container_dir,
        schemas_json=schemas_json,
    )
