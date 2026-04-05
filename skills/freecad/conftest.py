"""Shared fixtures for FreeCAD tests."""

import logging

import pytest
import pytest_bazel
from opentelemetry import trace

from util.oci import OciImage, load_oci_image
from util.testing.container_logs import LoggedContainer
from util.testing.otel_tracing import configure_tracing, export_traces

logger = logging.getLogger(__name__)

FREECAD_TEST = OciImage("_main/skills/freecad/freecad_test.rloc", "freecad-test:pinned")
FREECAD_HELPERS = "_main/skills/freecad/freecad_helpers.py"
XVFB_CMD = 'xvfb-run -a -s \\"-screen 0 1024x768x24\\"'

tracer = trace.get_tracer(__name__)


def pytest_configure(config: pytest.Config) -> None:
    configure_tracing(config)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    export_traces(session.config)


@pytest.fixture(scope="session")
def freecad_image() -> str:
    """Load FreeCAD test image into Docker daemon and return its tag."""
    return load_oci_image(FREECAD_TEST)


def freecad_exec(container: LoggedContainer, cmd: str) -> None:
    """Run a command in a FreeCAD container, asserting success."""
    with tracer.start_as_current_span("freecad_exec", attributes={"cmd": cmd}):
        result = container.exec(cmd)
        output = result.output.decode(errors="replace")
        print(output)
        assert result.exit_code == 0, f"Command failed (exit {result.exit_code}): {output[:500]}"
