"""Golden-file test: Part Design bearing block -> TechDraw + 3D renders."""

import shutil
from pathlib import Path

import pytest
import pytest_bazel

from skills.freecad.conftest import assert_run_ok
from skills.freecad.testing.compare import assert_dxf_equal, assert_pdf_equal, assert_png_equal, assert_svg_equal
from util.bazel.runfiles import get_required_path
from util.testing.undeclared_outputs import undeclared_outputs_dir

_BUILD_SCRIPT = "_main/skills/freecad/build_bearing_block.py"
_TECHDRAW_SCRIPT = "_main/skills/freecad/build_bearing_block_techdraw.py"
_RENDER_SCRIPT = "_main/skills/freecad/render_multi_angle.py"
_EXPORT_SCRIPT = "_main/skills/freecad/export_page.py"

_GOLDEN_DXF = "_main/skills/freecad/golden/bearing_block.dxf"
_GOLDEN_SVG = "_main/skills/freecad/golden/bearing_block.svg"
_GOLDEN_PDF = "_main/skills/freecad/golden/bearing_block.pdf"
_GOLDEN_FRONT_RIGHT = "_main/skills/freecad/golden/bearing_block_front_right.png"
_GOLDEN_BACK_LEFT = "_main/skills/freecad/golden/bearing_block_back_left.png"


@pytest.fixture(scope="module")
def bearing_block_outputs(tmp_path_factory: pytest.TempPathFactory, freecad_run, freecad_gui) -> Path:
    """Build bearing block, export TechDraw, render perspectives."""
    out_dir = tmp_path_factory.mktemp("bearing-block")
    uo = undeclared_outputs_dir() / "bearing-block"
    uo.mkdir(parents=True, exist_ok=True)

    # Stage 1: Build the Part Design model (pure freecadcmd, no GUI)
    result = freecad_run(get_required_path(_BUILD_SCRIPT), outdir=out_dir)
    assert_run_ok(result, "build_bearing_block.py", uo, "build")

    fcstd = out_dir / "bearing_block.FCStd"
    assert fcstd.exists(), "FCStd not generated — see build.stderr in test outputs"

    # Stage 2: Add TechDraw views + dimensions
    result = freecad_gui(get_required_path(_TECHDRAW_SCRIPT), outdir=out_dir, env={"INPUT": str(fcstd)})
    assert_run_ok(result, "build_bearing_block_techdraw.py", uo, "techdraw")

    # Stage 3: Export TechDraw to DXF/SVG/PDF
    result = freecad_gui(get_required_path(_EXPORT_SCRIPT), outdir=out_dir, env={"INPUT": str(fcstd)})
    assert_run_ok(result, "export_page.py", uo, "export")

    # Stage 4: Render multiple 3D perspectives
    result = freecad_gui(get_required_path(_RENDER_SCRIPT), outdir=out_dir, env={"INPUT": str(fcstd)})
    assert_run_ok(result, "render_multi_angle.py", uo, "render")

    for f in out_dir.iterdir():
        shutil.copy2(f, uo / f.name)

    return out_dir


def test_techdraw_dxf_golden(bearing_block_outputs: Path) -> None:
    assert_dxf_equal(bearing_block_outputs / "bearing_block.dxf", get_required_path(_GOLDEN_DXF))


def test_techdraw_svg_golden(bearing_block_outputs: Path) -> None:
    assert_svg_equal(bearing_block_outputs / "bearing_block.svg", get_required_path(_GOLDEN_SVG))


def test_techdraw_pdf_golden(bearing_block_outputs: Path) -> None:
    assert_pdf_equal(bearing_block_outputs / "bearing_block.pdf", get_required_path(_GOLDEN_PDF))


def test_render_front_right(bearing_block_outputs: Path) -> None:
    assert_png_equal(bearing_block_outputs / "bearing_block_front_right.png", get_required_path(_GOLDEN_FRONT_RIGHT))


def test_render_back_left(bearing_block_outputs: Path) -> None:
    assert_png_equal(bearing_block_outputs / "bearing_block_back_left.png", get_required_path(_GOLDEN_BACK_LEFT))


if __name__ == "__main__":
    pytest_bazel.main()
