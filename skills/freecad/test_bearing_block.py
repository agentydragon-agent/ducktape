"""Golden-file test: Part Design bearing block -> TechDraw + 3D renders."""

import shutil
from pathlib import Path

import pytest
import pytest_bazel

from skills.freecad.conftest import FREECAD_TEST
from skills.freecad.testing.compare import assert_dxf_equal, assert_pdf_equal, assert_png_equal, assert_svg_equal
from util.bazel.runfiles import get_required_path
from util.oci import load_oci_image
from util.testing.container_logs import LoggedContainer
from util.testing.undeclared_outputs import undeclared_outputs_dir

_BUILD_SCRIPT = "_main/skills/freecad/build_bearing_block.py"
_TECHDRAW_SCRIPT = "_main/skills/freecad/build_bearing_block_techdraw.py"
_RENDER_SCRIPT = "_main/skills/freecad/render_multi_angle.py"
_EXPORT_SCRIPT = "_main/skills/freecad/export_page.py"
_HELPERS_SCRIPT = "_main/skills/freecad/freecad_helpers.py"

_GOLDEN_DXF = "_main/skills/freecad/golden/bearing_block.dxf"
_GOLDEN_SVG = "_main/skills/freecad/golden/bearing_block.svg"
_GOLDEN_PDF = "_main/skills/freecad/golden/bearing_block.pdf"
_GOLDEN_FRONT_RIGHT = "_main/skills/freecad/golden/bearing_block_front_right.png"
_GOLDEN_BACK_LEFT = "_main/skills/freecad/golden/bearing_block_back_left.png"

_XVFB = 'xvfb-run -a -s \\"-screen 0 1024x768x24\\"'


@pytest.fixture(scope="module")
def bearing_block_outputs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build bearing block, export TechDraw, render perspectives."""
    tag = load_oci_image(FREECAD_TEST)
    tmp_path = tmp_path_factory.mktemp("freecad-bearing-block")

    scripts = [
        (get_required_path(_BUILD_SCRIPT), "/work/build_bearing_block.py"),
        (get_required_path(_TECHDRAW_SCRIPT), "/work/build_bearing_block_techdraw.py"),
        (get_required_path(_RENDER_SCRIPT), "/work/render_multi_angle.py"),
        (get_required_path(_EXPORT_SCRIPT), "/work/export_page.py"),
        (get_required_path(_HELPERS_SCRIPT), "/work/freecad_helpers.py"),
    ]
    volumes = [(str(src), dst, "ro") for src, dst in scripts] + [(str(tmp_path), "/output", "rw")]

    with LoggedContainer(
        tag,
        test_name="freecad-bearing-block",
        command="sleep infinity",
        volumes=volumes,
        docker_client_kw={"timeout": 300},
    ) as container:
        # Stage 1: Build the Part Design model
        result = container.exec('bash -c "OUTDIR=/output freecadcmd /work/build_bearing_block.py"')
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"Build failed (exit {result.exit_code}): {output[:500]}"

        # Stage 2: Add TechDraw page with 4 views + dimensions
        result = container.exec(
            f'bash -c "INPUT=/output/bearing_block.FCStd OUTDIR=/output '
            f'{_XVFB} freecadcmd /work/build_bearing_block_techdraw.py"'
        )
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"TechDraw failed (exit {result.exit_code}): {output[:3000]}"

        # Stage 3: Export TechDraw to DXF/SVG/PDF
        result = container.exec(
            f'bash -c "INPUT=/output/bearing_block.FCStd OUTDIR=/output {_XVFB} freecadcmd /work/export_page.py"'
        )
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"Export failed (exit {result.exit_code}): {output[:500]}"

        # Stage 4: Render multiple perspectives
        result = container.exec(
            f'bash -c "INPUT=/output/bearing_block.FCStd OUTDIR=/output {_XVFB} freecadcmd /work/render_multi_angle.py"'
        )
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"Render failed (exit {result.exit_code}): {output[:500]}"

    # Save outputs for debugging
    out_dir = undeclared_outputs_dir() / "bearing-block"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in tmp_path.iterdir():
        shutil.copy2(f, out_dir / f.name)

    return tmp_path


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
