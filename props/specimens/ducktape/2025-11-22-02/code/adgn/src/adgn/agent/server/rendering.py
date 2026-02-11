from __future__ import annotations

from importlib import resources

from jinja2 import Environment
from pydantic import BaseModel

from adgn.mcp.snapshots import ServerEntry


def _templates_pkg_name() -> str:
    """Resolve the templates package relative to this module.

    Avoid hard-coding the full package path by deriving '...agent.templates'
    from our own package ('...agent.server').
    """
    pkg = __package__ or "adgn.agent.server"
    base = pkg.rsplit(".", 1)[0]  # e.g., 'adgn.agent'
    return f"{base}.templates"


def render_compositor_instructions(states: dict[str, ServerEntry]) -> str:
    """Render grouped MCP server instructions/capabilities using a Jinja2 template.

    Passes raw typed states directly to the template; filtering/sorting is done in Jinja.
    Returns an empty string if there are no running servers with content.
    """
    if not states:
        return ""

    # Load template from package resources and render
    template_name = "compositor_instructions.md.j2"
    template_text = resources.files(_templates_pkg_name()).joinpath(template_name).read_text("utf-8")
    env = Environment(autoescape=False)

    # Filter: emit JSON using Pydantic's model_dump_json if available
    def _f_model_dump_json(value, *args, **kwargs):
        if isinstance(value, BaseModel):
            return value.model_dump_json(*args, **kwargs)
        # Fall back to str() if not a Pydantic model
        return str(value)

    env.filters["model_dump_json"] = _f_model_dump_json
    template = env.from_string(template_text)
    # Pass raw states for Jinja to consume with dictsort and attribute access
    out = template.render(states=states)
    # Jinja's Template.render returns str (or Markup, a str subclass when autoescape=True).
    assert isinstance(out, str)
    return out
