from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.properties.docker_env import PropertiesDockerWiring
from adgn.llm.properties.prompts.builder import build_check_prompt, build_role_prompt


def _dummy_wiring(defs_dir: Path | None = Path("/props")) -> PropertiesDockerWiring:
    # Minimal wiring sufficient for env line; no MCP servers used in prompt-only compose
    dummy_server = FastMCP("dummy")
    return PropertiesDockerWiring(
        server_spec=make_inproc_slot_spec(dummy_server),
        working_dir=Path("/"),
        definitions_container_dir=defs_dir,
        image_name="n/a",
    )


def test_build_check_prompt_renders_schemas():
    wiring = _dummy_wiring()
    text = build_check_prompt(
        "all files under src/**",
        wiring=wiring,
        allow_general_findings=False,
    )
    lines = text.splitlines()
    assert lines[0].startswith("# "), "expected H1 header at top of prompt"
    assert "Input Schemas:" in text
    assert "- Occurrence\n```json" in text
    assert "- LineRange\n```json" in text


def test_build_role_prompt_open_has_header_and_schemas():
    wiring = _dummy_wiring()
    text = build_role_prompt("open", "all files under src/**", wiring=wiring)
    assert text.startswith("# ")
    assert "Input Schemas:" in text
