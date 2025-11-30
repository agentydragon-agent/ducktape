from __future__ import annotations

from pydantic import TypeAdapter

from adgn.props.critic import CriticSubmitPayload, ReportedIssue
from adgn.props.docker_env import PropertiesDockerWiring
from adgn.props.grader import (
    CanonicalFPCoverage,
    CanonicalTPCoverage,
    CritiqueInputIssue,
    GradeMetrics,
    GradeSubmitInput,
    NovelIssueReasoning,
    ReportedIssueRatios,
)
from adgn.props.models.issue import IssueCore, LineRange, Occurrence
from adgn.props.specimens.registry import CanonicalIssue, KnownFalsePositive

from .schemas import build_input_schemas_json
from .util import render_prompt_template


def build_enforce_prompt(
    scope_text: str,
    *,
    wiring: PropertiesDockerWiring,
    schemas_json: dict[str, dict],
    supplemental_text: str | None = None,
) -> str:
    return render_prompt_template(
        "enforce.j2.md",
        scope_text=scope_text,
        supplemental_text=supplemental_text,
        static_action="edit",
        ambiguity_tail="avoid touching anything outside it unless required by the editing policy below.",
        wiring=wiring,
        schemas_json=schemas_json,
    )


def build_grade_from_json_prompt(
    *,
    canonical_issues: list[CanonicalIssue],
    critique_issues: list[CritiqueInputIssue],
    known_fps: list[KnownFalsePositive],
    submit_tool_name: str,
    wiring: PropertiesDockerWiring,
) -> str:
    """Compose grader prompt that consumes structured JSON and requires submit via grader_submit."""
    schemas_json = build_input_schemas_json(
        [
            Occurrence,
            LineRange,
            IssueCore,
            ReportedIssue,
            CriticSubmitPayload,
            GradeMetrics,
            GradeSubmitInput,
            CanonicalTPCoverage,
            CanonicalFPCoverage,
            NovelIssueReasoning,
            ReportedIssueRatios,
        ]
    )

    # Serialize lists to JSON strings before template rendering
    canonical_json = TypeAdapter(list[CanonicalIssue]).dump_json(canonical_issues, indent=2).decode()
    critique_json = TypeAdapter(list[CritiqueInputIssue]).dump_json(critique_issues, indent=2).decode()
    known_fps_json = TypeAdapter(list[KnownFalsePositive]).dump_json(known_fps, indent=2).decode()

    return render_prompt_template(
        "grade_from_json.j2.md",
        canonical_issues_json=canonical_json,
        critique_issues_json=critique_json,
        known_fps_json=known_fps_json,
        submit_tool_name=submit_tool_name,
        wiring=wiring,
        schemas_json=schemas_json,
    )
