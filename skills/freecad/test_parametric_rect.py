"""Golden-file test: parametric rectangle -> TechDraw -> DXF export via FreeCAD in Docker."""

from pathlib import Path

import docker
import pytest
import pytest_bazel

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

    client = docker.from_env()
    container = client.containers.run(
        _IMAGE_TAG,
        command=["xvfb-run", "-a", "-s", "-screen 0 1024x768x24", "freecadcmd", "/work/parametric_rect.py"],
        volumes={
            str(script): {"bind": "/work/parametric_rect.py", "mode": "ro"},
            str(tmp_path): {"bind": "/output", "mode": "rw"},
        },
        environment={"OUTDIR": "/output"},
        detach=True,
    )
    try:
        result = container.wait(timeout=120)
        stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")
        _save_output("container-stdout.log", stdout)
        _save_output("container-stderr.log", stderr)
        assert result["StatusCode"] == 0, f"Container failed (exit {result['StatusCode']})"
    finally:
        container.remove(force=True)

    actual_dxf = tmp_path / "rect.dxf"
    assert actual_dxf.exists(), "DXF not generated — check container logs in undeclared outputs"
    _save_output("actual-rect.dxf", actual_dxf.read_text())

    diff = compare_dxf_files(actual_dxf, golden)
    if diff is not None:
        _save_output("dxf-diff.txt", diff)
        pytest.fail(f"DXF mismatch — see undeclared outputs for diff:\n{diff[:500]}")


if __name__ == "__main__":
    pytest_bazel.main()
