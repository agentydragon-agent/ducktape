from __future__ import annotations

from typing import Literal

from adgn_llm.properties.docker_env import PropertiesDockerWiring
from adgn_llm.properties.prompt_utils import build_input_schemas_json
from adgn_llm.properties.specimen_utils import Occurrence, LineRange, IssueCore

# Reuse the existing Jinja renderers in cli.py to avoid duplicating template plumbing.
from adgn_llm.properties import cli as _cli


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
    schemas_json = build_input_schemas_json([Occurrence, LineRange, IssueCore])

    template = "discover.j2.md" if mode == "discover" else ("open.j2.md" if mode == "open" else "find.j2.md")
    return _cli._render_prompt_template(
        template,
        scope_text=scope_text,
        supplemental_text=supplemental_text,
        available_tools=available_tools or [],
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
    return build_role_prompt(
        mode,
        scope_text,
        wiring=wiring,
        supplemental_text=None,
        available_tools=available_tools,
    )


def build_grade_prompt(
    scope_text: str,
    canonical_text: str,
    critique_text: str,
    *,
    wiring: PropertiesDockerWiring,
) -> str:
    """Compose the grade prompt (pure).

    - Computes schemas_json internally
    - Returns the composed Markdown string
    """
    schemas_json = build_input_schemas_json([Occurrence, LineRange, IssueCore])
    return _cli.build_grade_prompt(
        scope_text,
        canonical_text,
        critique_text,
        wiring=wiring,
        schemas_json=schemas_json,
    )
