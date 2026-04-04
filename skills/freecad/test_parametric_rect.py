"""Golden-file test: parametric rectangle -> TechDraw -> DXF export via FreeCAD in Docker."""

from pathlib import Path

import pytest
import pytest_bazel
from testcontainers.core.container import DockerContainer

from skills.freecad.compare_dxf import compare_dxf_files
from util.bazel.runfiles import get_required_path
from util.oci import load_image
from util.testing.undeclared_outputs import undeclared_outputs_dir

_IMAGE_TAG = "freecad-test:pinned"
_TARBALL = "_main/skills/freecad/freecad_test_load/tarball.tar"
_SCRIPT = "_main/skills/freecad/parametric_rect.py"
_GOLDEN = "_main/skills/freecad/golden/rect.dxf"


def _save_output(name: str, content: str) -> None:
    out_dir = undeclared_outputs_dir() / "freecad-parametric-rect"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(content)


def test_parametric_rect(tmp_path: Path) -> None:
    load_image(_TARBALL)
    script = get_required_path(_SCRIPT)
    golden = get_required_path(_GOLDEN)

    # bash -c wrapping ensures Xvfb cleanup after freecadcmd's os._exit(0)
    container = (
        DockerContainer(_IMAGE_TAG)
        .with_volume_mapping(str(script), "/work/parametric_rect.py", "ro")
        .with_volume_mapping(str(tmp_path), "/output", "rw")
        .with_env("OUTDIR", "/output")
        .with_command("bash -c 'xvfb-run -a -s \"-screen 0 1024x768x24\" freecadcmd /work/parametric_rect.py'")
    )

    with container:
        stdout = container.get_logs()[0].decode(errors="replace")
        stderr = container.get_logs()[1].decode(errors="replace")
        _save_output("container-stdout.log", stdout)
        _save_output("container-stderr.log", stderr)

    actual_dxf = tmp_path / "rect.dxf"
    assert actual_dxf.exists(), "DXF not generated — check container logs in undeclared outputs"
    _save_output("actual-rect.dxf", actual_dxf.read_text())

    diff = compare_dxf_files(actual_dxf, golden)
    if diff is not None:
        _save_output("dxf-diff.txt", diff)
        pytest.fail(f"DXF mismatch — see undeclared outputs for diff:\n{diff[:500]}")


if __name__ == "__main__":
    pytest_bazel.main()
