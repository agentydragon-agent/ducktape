from __future__ import annotations

from typing import Literal

from adgn.props.critic import CriticSubmitPayload, ReportedIssue
from adgn.props.docker_env import PropertiesDockerWiring
from adgn.props.grader import CoverageCredit, GradeMetrics, GradeSubmitInput, GradeSubmitPayload
from adgn.props.ids import CANON_FP_PREFIX, CANON_TP_PREFIX, CRIT_PREFIX
from adgn.props.models.issue import IssueCore, LineRange, Occurrence

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
        [Occurrence, LineRange, IssueCore, ReportedIssue, CriticSubmitPayload, GradeMetrics, GradeSubmitPayload]
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
        [Occurrence, LineRange, IssueCore, ReportedIssue, CriticSubmitPayload, GradeMetrics, GradeSubmitPayload]
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
    canonical_json: str,
    critique_json: str,
    known_fp_json: str | None,
    submit_tool_name: str,
    wiring: PropertiesDockerWiring,
) -> str:
    """Compose grader prompt that consumes structured JSON and requires submit via grader_submit.

    - canonical_json: JSON block of canonical positives (IssueCore+Occurrence) list or mapping
    - critique_json: JSON block produced by the unified run (critic output)
    - known_fp_json: JSON block of known false positives (IssueCore+Occurrence) list or mapping
    - submit_tool_name: fully-qualified MCP function name for grader_submit.submit_result
    """
    schemas_json = build_input_schemas_json(
        [
            Occurrence,
            LineRange,
            IssueCore,
            ReportedIssue,
            CriticSubmitPayload,
            GradeMetrics,
            GradeSubmitInput,
            CoverageCredit,
        ]
    )
    # Pass shared ID prefix constants into the template to avoid drift

    return render_prompt_template(
        "grade_from_json.j2.md",
        scope_text=scope_text,
        canonical_json=canonical_json,
        critique_json=critique_json,
        known_fp_json=known_fp_json or "",
        submit_tool_name=submit_tool_name,
        canon_tp_prefix=CANON_TP_PREFIX,
        canon_fp_prefix=CANON_FP_PREFIX,
        crit_prefix=CRIT_PREFIX,
        wiring=wiring,
        schemas_json=schemas_json,
    )
