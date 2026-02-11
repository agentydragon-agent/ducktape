from __future__ import annotations

from importlib import resources

from hamcrest import all_of, assert_that, contains_string
from mcp import types

from adgn.agent.server.rendering import render_compositor_instructions
from adgn.mcp.snapshots import RunningServerEntry


def test_template_packaged() -> None:
    # Ensure the template is available via importlib.resources
    pkg = "adgn.agent.templates"
    text = resources.files(pkg).joinpath("compositor_instructions.md.j2").read_text("utf-8")
    assert "Instructions" in text


def test_render_empty_states_returns_empty() -> None:
    out = render_compositor_instructions({})
    assert out == ""


def test_render_single_running_with_instructions() -> None:
    init = types.InitializeResult(
        protocolVersion="1.0",
        capabilities=types.ServerCapabilities(),
        serverInfo=types.Implementation(name="docker_exec", version="0.0.0"),
        instructions="Hello world",
    )
    state = RunningServerEntry(initialize=init, tools=[])
    out = render_compositor_instructions({"docker_exec": state})
    assert_that(
        out,
        all_of(
            contains_string("The following MCP servers"),
            contains_string("# docker_exec"),
            contains_string("## Instructions"),
            contains_string("Hello world"),
        ),
    )
