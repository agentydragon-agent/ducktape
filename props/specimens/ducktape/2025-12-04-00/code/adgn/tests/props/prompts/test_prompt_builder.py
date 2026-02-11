from __future__ import annotations

from pathlib import Path

from fastmcp.server import FastMCP
import pytest

from adgn.props.docker_env import PropertiesDockerWiring
from adgn.props.prompts.util import build_standard_context, render_prompt_template


@pytest.fixture
def dummy_wiring() -> PropertiesDockerWiring:
    """Minimal wiring sufficient for env line; no MCP servers used in prompt-only compose."""
    dummy_server = FastMCP("dummy")
    return PropertiesDockerWiring(
        server_factory=lambda: dummy_server,
        working_dir=Path("/"),
        definitions_container_dir=Path("/props"),
        image_name="n/a",
    )


def test_find_prompt_renders_schemas(dummy_wiring: PropertiesDockerWiring):
    """Test that find.j2.md template renders with schemas."""
    files = [Path("src/foo.py"), Path("src/bar.py")]
    context = build_standard_context(files=files, wiring=dummy_wiring)
    text = render_prompt_template("find.j2.md", **context)
    lines = text.splitlines()
    assert lines[0].startswith("# "), "expected H1 header at top of prompt"
    assert "Input Schemas:" in text
    assert "- Occurrence\n```json" in text
    assert "- LineRange\n```json" in text


def test_open_prompt_has_header_and_schemas(dummy_wiring: PropertiesDockerWiring):
    """Test that open.j2.md template renders with schemas."""
    files = [Path("src/foo.py"), Path("src/bar.py")]
    context = build_standard_context(files=files, wiring=dummy_wiring)
    text = render_prompt_template("open.j2.md", **context)
    assert text.startswith("# ")
    assert "Input Schemas:" in text
