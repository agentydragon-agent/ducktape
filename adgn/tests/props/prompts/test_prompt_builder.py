from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from adgn.mcp._shared.constants import WORKING_DIR
from adgn.props.prompts.util import build_standard_context, render_prompt_template

if TYPE_CHECKING:
    pass


class MockCompositor:
    """Minimal mock compositor for prompt-only tests (no MCP servers needed)."""

    @property
    def working_dir(self) -> Path:
        return WORKING_DIR

    @property
    def definitions_container_dir(self) -> Path | None:
        return Path("/props")


@pytest.fixture
def mock_compositor() -> MockCompositor:
    """Mock compositor sufficient for template rendering; no Docker/MCP servers used."""
    return MockCompositor()


def test_find_prompt_renders_schemas(mock_compositor: MockCompositor):
    """Test that find.j2.md template renders with schemas."""
    files = [Path("src/foo.py"), Path("src/bar.py")]
    context = build_standard_context(files=files, compositor=mock_compositor)  # type: ignore[arg-type]
    text = render_prompt_template("prompts/find.j2.md", **context)
    lines = text.splitlines()
    assert lines[0].startswith("# "), "expected H1 header at top of prompt"
    assert "Input Schemas:" in text
    assert "- Occurrence\n```json" in text
    assert "- LineRange\n```json" in text


def test_open_prompt_has_header_and_schemas(mock_compositor: MockCompositor):
    """Test that open.j2.md template renders with schemas."""
    files = [Path("src/foo.py"), Path("src/bar.py")]
    context = build_standard_context(files=files, compositor=mock_compositor)  # type: ignore[arg-type]
    text = render_prompt_template("prompts/open.j2.md", **context)
    assert text.startswith("# ")
    assert "Input Schemas:" in text
