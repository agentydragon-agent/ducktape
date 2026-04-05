"""Golden-file test: render DXF to PNG and compare against golden PNG.

Uses a pixel diff threshold to tolerate minor rendering differences
across platforms (font availability, matplotlib version, anti-aliasing).
"""

from pathlib import Path

import pytest_bazel
from opentelemetry import trace

from skills.freecad.render_dxf import render_dxf
from skills.freecad.testing.compare import assert_png_equal
from util.bazel.runfiles import get_required_path

_GOLDEN_DXF = "_main/skills/freecad/golden/compound.dxf"
_GOLDEN_PNG = "_main/skills/freecad/golden/compound.png"

tracer = trace.get_tracer(__name__)


def test_render_compound(tmp_path: Path) -> None:
    golden_dxf = get_required_path(_GOLDEN_DXF)
    golden_png_path = get_required_path(_GOLDEN_PNG)
    actual_png = tmp_path / "compound.png"

    with tracer.start_as_current_span("render_dxf"):
        render_dxf(golden_dxf, actual_png)

    with tracer.start_as_current_span("compare_golden_png"):
        assert_png_equal(actual_png, golden_png_path)


if __name__ == "__main__":
    pytest_bazel.main()
