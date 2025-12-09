from __future__ import annotations

from importlib import resources

from jinja2 import Environment
from pydantic import BaseModel

from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.snapshots import ServerEntry


def render_compositor_instructions(states: dict[str, ServerEntry]) -> str:
    """Render grouped MCP server instructions/capabilities using a Jinja2 template.

    Passes raw typed states directly to the template; filtering/sorting is done in Jinja.
    Returns an empty string if there are no running servers with content.

    Args:
        states: Dictionary of server names to ServerEntry objects
    """
    if not states:
        return ""

    # Compute example tool using canonical naming helper with placeholder names
    example_tool = build_mcp_function("server_name", "tool_name")

    # Load template from package resources and render
    template_name = "compositor_instructions.md.j2"
    template_pkg = "adgn.mcp.compositor.templates"
    template_text = resources.files(template_pkg).joinpath(template_name).read_text("utf-8")
    env = Environment(autoescape=False)

    # Filter: emit JSON using Pydantic's model_dump_json if available
    def _f_model_dump_json(value, *args, **kwargs):
        if isinstance(value, BaseModel):
            return value.model_dump_json(*args, **kwargs)
        # Fall back to str() if not a Pydantic model
        return str(value)

    env.filters["model_dump_json"] = _f_model_dump_json
    template = env.from_string(template_text)
    # Pass raw states and example_tool for Jinja to consume
    out = template.render(states=states, example_tool=example_tool)
    # Jinja's Template.render returns str (or Markup, a str subclass when autoescape=True).
    assert isinstance(out, str)
    return out
