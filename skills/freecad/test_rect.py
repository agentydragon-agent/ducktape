"""Test: FreeCAD AppImage creates a rectangle DXF without Docker or Xvfb."""

import tempfile
from pathlib import Path

import pytest_bazel

from skills.freecad.conftest import assert_run_ok
from util.bazel.runfiles import get_required_path
from util.testing.undeclared_outputs import undeclared_outputs_dir

_RECT_SCRIPT = "_main/skills/freecad/rect.py"


def test_rect_dxf(freecad_run) -> None:
    script = get_required_path(_RECT_SCRIPT)
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        uo = undeclared_outputs_dir() / "rect"
        uo.mkdir(parents=True, exist_ok=True)
        result = freecad_run(script, out_dir)
        assert_run_ok(result, "rect.py", uo, "rect")

        dxf = out_dir / "rect.dxf"
        assert dxf.exists(), "rect.dxf not produced — see rect.stderr in test outputs"
        assert dxf.stat().st_size > 100
        content = dxf.read_text()
        assert "LINE" in content, "Expected LINE entities in DXF"
        assert content.count("LINE") >= 4, "Expected at least 4 LINE entities for rectangle"


if __name__ == "__main__":
    pytest_bazel.main()
