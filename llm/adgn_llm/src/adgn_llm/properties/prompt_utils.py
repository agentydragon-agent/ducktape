from __future__ import annotations

from jinja2 import Environment, PackageLoader, select_autoescape


def get_templates_env() -> Environment:
    """Load prompt templates from the installed package using importlib.resources.

    Templates live under the adgn_llm.properties.prompts package directory.
    """
    return Environment(
        loader=PackageLoader("adgn_llm.properties", "prompts"),
        autoescape=select_autoescape(["md", "markdown", "txt", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_prompt_template(name: str, **ctx: object) -> str:
    env = get_templates_env()
    tmpl = env.get_template(name)
    return str(tmpl.render(**ctx)).strip()
