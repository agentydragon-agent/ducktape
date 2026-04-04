"""Golden-file test: 3D cube with hole -> FCStd -> render PNG via FreeCAD in Docker."""

import shutil
from pathlib import Path

import pytest_bazel
from PIL import Image

from util.bazel.runfiles import get_required_path
from util.oci import load_image
from util.testing.container_logs import LoggedContainer
from util.testing.undeclared_outputs import undeclared_outputs_dir

_IMAGE_TAG = "freecad-test:pinned"
_TARBALL = "_main/skills/freecad/freecad_test_load/tarball.tar"
_BUILD_SCRIPT = "_main/skills/freecad/build_cube_with_hole.py"
_RENDER_SCRIPT = "_main/skills/freecad/render_fcstd.py"
_GOLDEN = "_main/skills/freecad/golden/cube_with_hole.png"

# Maximum fraction of differing pixel channels tolerated.
_MAX_DIFF_FRACTION = 0.02


def test_render_3d(tmp_path: Path) -> None:
    load_image(_TARBALL)
    build_script = get_required_path(_BUILD_SCRIPT)
    render_script = get_required_path(_RENDER_SCRIPT)
    golden_path = get_required_path(_GOLDEN)

    with LoggedContainer(
        _IMAGE_TAG,
        test_name="freecad-3d-build",
        command="sleep infinity",
        volumes=[(str(build_script), "/work/build_cube_with_hole.py", "ro"), (str(tmp_path), "/output", "rw")],
        docker_client_kw={"timeout": 120},
    ) as container:
        result = container.exec('bash -c "OUTDIR=/output freecadcmd /work/build_cube_with_hole.py"')
        assert result.exit_code == 0, (
            f"build failed (exit {result.exit_code}): {result.output.decode(errors='replace')[:500]}"
        )

    fcstd = tmp_path / "cube_with_hole.FCStd"
    assert fcstd.exists(), "FCStd not generated — check container logs"

    with LoggedContainer(
        _IMAGE_TAG,
        test_name="freecad-3d-render",
        command="sleep infinity",
        volumes=[
            (str(render_script), "/work/render_fcstd.py", "ro"),
            (str(fcstd), "/work/cube_with_hole.FCStd", "ro"),
            (str(tmp_path), "/output", "rw"),
        ],
        docker_client_kw={"timeout": 120},
    ) as container:
        result = container.exec(
            'bash -c "INPUT=/work/cube_with_hole.FCStd OUTDIR=/output '
            'xvfb-run -a -s \\"-screen 0 1024x768x24\\" freecadcmd /work/render_fcstd.py"'
        )
        assert result.exit_code == 0, (
            f"render failed (exit {result.exit_code}): {result.output.decode(errors='replace')[:500]}"
        )

    actual_png = tmp_path / "cube_with_hole.png"
    assert actual_png.exists(), "PNG not generated — check container logs"

    # Save rendered output for debugging
    out_dir = undeclared_outputs_dir() / "render-3d"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(actual_png, out_dir / "actual.png")

    # Compare against golden
    actual = Image.open(actual_png).convert("RGB")
    golden = Image.open(golden_path).convert("RGB")
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
