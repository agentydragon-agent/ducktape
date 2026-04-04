"""Golden-file test: parametric rectangle -> TechDraw -> DXF export via FreeCAD in Docker."""

from pathlib import Path

import pytest
import pytest_bazel

from skills.freecad.compare_dxf import compare_dxf_files
from util.bazel.runfiles import get_required_path
from util.oci import load_image
from util.testing.container_logs import LoggedContainer

_IMAGE_TAG = "freecad-test:pinned"
_TARBALL = "_main/skills/freecad/freecad_test_load/tarball.tar"
_SCRIPT = "_main/skills/freecad/parametric_rect.py"
_GOLDEN = "_main/skills/freecad/golden/rect.dxf"


def test_parametric_rect(tmp_path: Path) -> None:
    load_image(_TARBALL)
    script = get_required_path(_SCRIPT)
    golden = get_required_path(_GOLDEN)

    with LoggedContainer(
        _IMAGE_TAG,
        test_name="freecad-rect",
        command="sleep infinity",
        volumes=[(str(script), "/work/parametric_rect.py", "ro"), (str(tmp_path), "/output", "rw")],
        docker_client_kw={"timeout": 120},
    ) as container:
        result = container.exec(
            'bash -c "OUTDIR=/output xvfb-run -a -s \\"-screen 0 1024x768x24\\" freecadcmd /work/parametric_rect.py"'
        )
        assert result.exit_code == 0, (
            f"freecadcmd failed (exit {result.exit_code}): {result.output.decode(errors='replace')[:500]}"
        )

    actual_dxf = tmp_path / "rect.dxf"
    assert actual_dxf.exists(), "DXF not generated — check container logs in undeclared outputs"

    diff = compare_dxf_files(actual_dxf, golden)
    if diff is not None:
        pytest.fail(f"DXF mismatch:\n{diff[:500]}")


if __name__ == "__main__":
    pytest_bazel.main()
