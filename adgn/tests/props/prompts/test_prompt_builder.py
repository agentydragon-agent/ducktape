from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from adgn.mcp._shared.constants import WORKING_DIR
from adgn.mcp._shared.container_session import ContainerOptions
from adgn.props.docker_env import PropertiesDockerWiring
from adgn.props.prompts.util import build_standard_context, render_prompt_template

if TYPE_CHECKING:
    from adgn.mcp.exec.docker.server import ContainerExecServer


@pytest.fixture
def dummy_wiring() -> PropertiesDockerWiring:
    """Minimal wiring sufficient for env line; no MCP servers used in prompt-only compose."""

    def make_dummy_server() -> ContainerExecServer:
        """Lazy import to avoid Docker client initialization in prompt-only tests."""
        from adgn.mcp.exec.docker.server import ContainerExecServer

        return ContainerExecServer(
            ContainerOptions(
                image="dummy:latest",
                working_dir=WORKING_DIR,
                binds={},
                environment={},
                ephemeral=True,
                network_mode="none",
            ),
            docker_client=None,  # type: ignore[arg-type]  # Never actually used in these prompt tests
        )

    return PropertiesDockerWiring(
        server_factory=make_dummy_server,
        working_dir=Path("/"),
        definitions_container_dir=Path("/props"),
        image_name="dummy:latest",
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
