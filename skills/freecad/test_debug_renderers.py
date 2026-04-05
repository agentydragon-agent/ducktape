"""Golden-file test: debug renderers produce color-coded edge/face PNGs."""

import shutil
from pathlib import Path

import pytest
import pytest_bazel
from PIL import Image

from skills.freecad.conftest import FREECAD_TEST
from skills.freecad.testing.compare import assert_png_equal
from util.bazel.runfiles import get_required_path
from util.oci import load_oci_image
from util.testing.container_logs import LoggedContainer
from util.testing.undeclared_outputs import undeclared_outputs_dir

_BUILD_SCRIPT = "_main/skills/freecad/build_bearing_block.py"
_TECHDRAW_SCRIPT = "_main/skills/freecad/build_bearing_block_techdraw.py"
_HELPERS_SCRIPT = "_main/skills/freecad/freecad_helpers.py"
_DEBUG_EDGES_SCRIPT = "_main/skills/freecad/render_debug_edges.py"
_DEBUG_FACES_SCRIPT = "_main/skills/freecad/render_debug_faces.py"

_GOLDEN_EDGES_FRONT = "_main/skills/freecad/golden/FrontView_debug_edges.png"
_GOLDEN_FACES = "_main/skills/freecad/golden/debug_faces.png"

_XVFB = 'xvfb-run -a -s \\"-screen 0 1024x768x24\\"'

# Debug renderers use QPainter text rendering which varies more than 3D renders.
_DEBUG_MAX_DIFF = 0.05


@pytest.fixture(scope="module")
def debug_outputs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build bearing block, add TechDraw, run debug renderers."""
    tag = load_oci_image(FREECAD_TEST)
    tmp_path = tmp_path_factory.mktemp("freecad-debug-renderers")

    scripts = [
        (get_required_path(_BUILD_SCRIPT), "/work/build_bearing_block.py"),
        (get_required_path(_TECHDRAW_SCRIPT), "/work/build_bearing_block_techdraw.py"),
        (get_required_path(_HELPERS_SCRIPT), "/work/freecad_helpers.py"),
        (get_required_path(_DEBUG_EDGES_SCRIPT), "/work/render_debug_edges.py"),
        (get_required_path(_DEBUG_FACES_SCRIPT), "/work/render_debug_faces.py"),
    ]
    volumes = [(str(src), dst, "ro") for src, dst in scripts] + [(str(tmp_path), "/output", "rw")]

    with LoggedContainer(
        tag,
        test_name="freecad-debug-renderers",
        command="sleep infinity",
        volumes=volumes,
        docker_client_kw={"timeout": 300},
    ) as container:
        # Build the Part Design model
        result = container.exec('bash -c "OUTDIR=/output freecadcmd /work/build_bearing_block.py"')
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"Build failed (exit {result.exit_code}): {output[:500]}"

        # Add TechDraw views (needed for debug edges)
        result = container.exec(
            f'bash -c "INPUT=/output/bearing_block.FCStd OUTDIR=/output '
            f'{_XVFB} freecadcmd /work/build_bearing_block_techdraw.py"'
        )
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"TechDraw failed (exit {result.exit_code}): {output[:500]}"

        # Render debug edges (all views)
        result = container.exec(
            f'bash -c "INPUT=/output/bearing_block.FCStd OUTDIR=/output {_XVFB} freecadcmd /work/render_debug_edges.py"'
        )
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"Debug edges failed (exit {result.exit_code}): {output[:500]}"

        # Render debug faces
        result = container.exec(
            f'bash -c "INPUT=/output/bearing_block.FCStd OUTDIR=/output {_XVFB} freecadcmd /work/render_debug_faces.py"'
        )
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"Debug faces failed (exit {result.exit_code}): {output[:500]}"

    # Save outputs for debugging
    out_dir = undeclared_outputs_dir() / "debug-renderers"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in tmp_path.iterdir():
        shutil.copy2(f, out_dir / f.name)

    return tmp_path


def test_debug_edges_produces_png(debug_outputs: Path) -> None:
    """Debug edge renderer produces a non-trivial PNG with colored edges."""
    actual = debug_outputs / "FrontView_debug_edges.png"
    assert actual.exists(), "FrontView debug edges PNG not generated"
    img = Image.open(actual)
    assert img.size == (1800, 1350), f"Unexpected size: {img.size}"
    # Verify it's not blank (has non-white pixels = colored edges)
    pixels = img.convert("RGB").tobytes()
    non_white = sum(
        1 for i in range(0, len(pixels), 3) if pixels[i] != 255 or pixels[i + 1] != 255 or pixels[i + 2] != 255
    )
    assert non_white > 100, "Debug edges PNG appears blank (no colored edges)"
    assert_png_equal(actual, get_required_path(_GOLDEN_EDGES_FRONT), max_diff_fraction=_DEBUG_MAX_DIFF)


def test_debug_faces_produces_png(debug_outputs: Path) -> None:
    """Debug face renderer produces a non-trivial PNG with colored faces."""
    actual = debug_outputs / "debug_faces.png"
    assert actual.exists(), "Debug faces PNG not generated"
    img = Image.open(actual)
    assert img.size == (800, 600), f"Unexpected size: {img.size}"
    # Verify it has multiple distinct colors (not monochrome)
    colors = img.convert("RGB").getcolors(maxcolors=10000)
    assert colors is not None, "Could not count colors"
    # A properly colored face render should have many colors (>50 distinct RGB values)
    assert len(colors) > 50, f"Only {len(colors)} distinct colors — faces may not be colored"
    assert_png_equal(actual, get_required_path(_GOLDEN_FACES), max_diff_fraction=_DEBUG_MAX_DIFF)


if __name__ == "__main__":
    pytest_bazel.main()
