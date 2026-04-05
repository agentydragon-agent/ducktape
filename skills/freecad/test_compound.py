"""Golden-file test: compound shape (walls + table) -> TechDraw -> DXF/SVG/PDF export."""

import shutil
from pathlib import Path

import pytest
import pytest_bazel
from opentelemetry import trace

from skills.freecad.conftest import FREECAD_HELPERS, FREECAD_TEST, XVFB_CMD, freecad_exec
from skills.freecad.testing.compare import assert_dxf_equal, assert_pdf_equal, assert_svg_equal
from util.bazel.runfiles import get_required_path
from util.oci import load_oci_image
from util.testing.container_logs import LoggedContainer
from util.testing.undeclared_outputs import undeclared_outputs_dir

_BUILD_SCRIPT = "_main/skills/freecad/build_compound.py"
_EXPORT_SCRIPT = "_main/skills/freecad/export_page.py"
_GOLDEN_DXF = "_main/skills/freecad/golden/compound.dxf"
_GOLDEN_SVG = "_main/skills/freecad/golden/compound.svg"
_GOLDEN_PDF = "_main/skills/freecad/golden/compound.pdf"

tracer = trace.get_tracer(__name__)


@pytest.fixture(scope="module")
def compound_outputs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build compound shape and export all formats."""
    with tracer.start_as_current_span("load_oci_image"):
        tag = load_oci_image(FREECAD_TEST)
    tmp_path = tmp_path_factory.mktemp("freecad-compound")

    with (
        tracer.start_as_current_span("container_lifecycle"),
        LoggedContainer(
            tag,
            test_name="freecad-compound",
            command="sleep infinity",
            volumes=[
                (str(get_required_path(FREECAD_HELPERS)), "/work/freecad_helpers.py", "ro"),
                (str(get_required_path(_BUILD_SCRIPT)), "/work/build_compound.py", "ro"),
                (str(get_required_path(_EXPORT_SCRIPT)), "/work/export_page.py", "ro"),
                (str(tmp_path), "/output", "rw"),
            ],
            docker_client_kw={"timeout": 120},
        ) as container,
    ):
        freecad_exec(container, f'bash -c "OUTDIR=/output {XVFB_CMD} freecadcmd /work/build_compound.py"')
        freecad_exec(
            container,
            f'bash -c "INPUT=/output/compound.FCStd OUTDIR=/output {XVFB_CMD} freecadcmd /work/export_page.py"',
        )

    out_dir = undeclared_outputs_dir() / "compound"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in ("compound.dxf", "compound.svg", "compound.pdf"):
        src = tmp_path / f
        if src.exists():
            shutil.copy2(src, out_dir / f)

    return tmp_path


def test_dxf_golden(compound_outputs: Path) -> None:
    with tracer.start_as_current_span("assert_dxf_equal"):
        actual = compound_outputs / "compound.dxf"
        assert actual.exists(), "DXF not generated"
        assert_dxf_equal(actual, get_required_path(_GOLDEN_DXF))


def test_svg_golden(compound_outputs: Path) -> None:
    with tracer.start_as_current_span("assert_svg_equal"):
        actual = compound_outputs / "compound.svg"
        assert actual.exists(), "SVG not generated"
        assert_svg_equal(actual, get_required_path(_GOLDEN_SVG))


def test_pdf_golden(compound_outputs: Path) -> None:
    with tracer.start_as_current_span("assert_pdf_equal"):
        actual = compound_outputs / "compound.pdf"
        assert actual.exists(), "PDF not generated"
        assert_pdf_equal(actual, get_required_path(_GOLDEN_PDF))


if __name__ == "__main__":
    pytest_bazel.main()
