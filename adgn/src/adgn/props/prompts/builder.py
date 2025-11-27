from __future__ import annotations

from typing import Literal

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

from .util import build_input_schemas_json, render_prompt_template


def build_role_prompt(
    mode: Literal["find", "open", "discover"],
    scope_text: str,
    *,
    wiring: PropertiesDockerWiring,
    supplemental_text: str | None = None,
    available_tools: list[str] | None = None,
) -> str:
    """Pure prompt compose for find/open/discover.

    - Computes schemas_json internally (full map needed by properties prompts)
    - Delegates to the shared renderer with the correct template selection
    - No stdout or subprocess; returns the composed Markdown string
    """
    # Compute the schemas map once here; templates pick header_schema_names
    schemas_json = build_input_schemas_json(
        [Occurrence, LineRange, IssueCore, ReportedIssue, CriticSubmitPayload, GradeMetrics, GradeSubmitInput]
    )

    template = "discover.j2.md" if mode == "discover" else ("open.j2.md" if mode == "open" else "find.j2.md")
    return render_prompt_template(
        template,
        scope_text=scope_text,
        supplemental_text=supplemental_text,
        available_tools=(available_tools if available_tools is not None else []),
        static_action="analyze",
        ambiguity_tail="do not include anything outside it.",
        wiring=wiring,
        schemas_json=schemas_json,
    )


def build_check_prompt(
    scope_text: str,
    *,
    wiring: PropertiesDockerWiring,
    allow_general_findings: bool = False,
    available_tools: list[str] | None = None,
) -> str:
    """Convenience for non-specimen check prompts (RO analysis).

    - mode: "open" when allow_general_findings is True, otherwise "find"
    - Pure compose (no agent run)
    """
    mode: Literal["open", "find"] = "open" if allow_general_findings else "find"
    return build_role_prompt(mode, scope_text, wiring=wiring, supplemental_text=None, available_tools=available_tools)


def build_grade_prompt(
    scope_text: str, canonical_text: str, critique_text: str, *, wiring: PropertiesDockerWiring
) -> str:
    """Compose the grade prompt (pure).

    - Computes schemas_json internally
    - Returns the composed Markdown string
    """
    schemas_json = build_input_schemas_json(
        [Occurrence, LineRange, IssueCore, ReportedIssue, CriticSubmitPayload, GradeMetrics, GradeSubmitInput]
    )
    return render_prompt_template(
        "grade.j2.md",
        scope_text=scope_text,
        canonical_text=canonical_text,
        critique_text=critique_text,
        static_action="use for context only (do not re-scan code)",
        ambiguity_tail="you are not re-running analysis; only use it for reference while matching.",
        wiring=wiring,
        schemas_json=schemas_json,
    )


def build_find_prompt(
    scope_text: str,
    *,
    wiring: PropertiesDockerWiring,
    schemas_json: dict[str, dict],
    supplemental_text: str | None = None,
    available_tools: list[str] | None = None,
) -> str:
    return render_prompt_template(
        "find.j2.md",
        scope_text=scope_text,
        supplemental_text=supplemental_text,
        available_tools=(available_tools if available_tools is not None else []),
        static_action="analyze",
        ambiguity_tail="do not include anything outside it.",
        wiring=wiring,
        schemas_json=schemas_json,
    )


def build_open_review_prompt(
    scope_text: str,
    *,
    wiring: PropertiesDockerWiring,
    schemas_json: dict[str, dict],
    supplemental_text: str | None = None,
    available_tools: list[str] | None = None,
) -> str:
    return render_prompt_template(
        "open.j2.md",
        scope_text=scope_text,
        supplemental_text=supplemental_text,
        available_tools=(available_tools if available_tools is not None else []),
        static_action="analyze",
        ambiguity_tail="do not include anything outside it.",
        wiring=wiring,
        schemas_json=schemas_json,
    )


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
    scope_text: str,
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
    return render_prompt_template(
        "grade_from_json.j2.md",
        scope_text=scope_text,
        canonical_issues=canonical_issues,
        critique_issues=critique_issues,
        known_fps=known_fps,
        submit_tool_name=submit_tool_name,
        wiring=wiring,
        schemas_json=schemas_json,
    )
