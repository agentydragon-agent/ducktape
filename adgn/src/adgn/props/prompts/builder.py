from __future__ import annotations

from adgn.props.docker_env import PropertiesDockerCompositor

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
