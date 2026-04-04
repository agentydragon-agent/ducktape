"""Golden-file test: render DXF to PNG and compare against golden PNG.

Uses a pixel diff threshold to tolerate minor rendering differences
across platforms (font availability, matplotlib version, anti-aliasing).
"""

from pathlib import Path

import pytest_bazel
from PIL import Image

from skills.freecad.render_dxf import render_dxf
from util.bazel.runfiles import get_required_path

_GOLDEN_DXF = "_main/skills/freecad/golden/rect.dxf"
_GOLDEN_PNG = "_main/skills/freecad/golden/rect.png"

# Maximum fraction of differing pixel channels tolerated.
_MAX_DIFF_FRACTION = 0.02


def test_render_rect(tmp_path: Path) -> None:
    golden_dxf = get_required_path(_GOLDEN_DXF)
    golden_png_path = get_required_path(_GOLDEN_PNG)
    actual_png = tmp_path / "rect.png"

    render_dxf(golden_dxf, actual_png)

    actual = Image.open(actual_png).convert("RGB")
    golden = Image.open(golden_png_path).convert("RGB")
    assert actual.size == golden.size, f"Size mismatch: {actual.size} vs {golden.size}"

    a_data = actual.tobytes()
    g_data = golden.tobytes()
    differing = sum(1 for a, g in zip(a_data, g_data, strict=True) if a != g)
    diff_fraction = differing / len(a_data)
    assert diff_fraction <= _MAX_DIFF_FRACTION, (
        f"Rendered PNG differs from golden by {diff_fraction:.1%} (threshold {_MAX_DIFF_FRACTION:.1%})"
    )


if __name__ == "__main__":
    pytest_bazel.main()
