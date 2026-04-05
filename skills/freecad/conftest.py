"""Shared fixtures for FreeCAD tests."""

import json
import logging

import pytest
import pytest_bazel
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from util.oci import OciImage, load_oci_image
from util.testing.container_logs import LoggedContainer
from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

FREECAD_TEST = OciImage("_main/skills/freecad/freecad_test.rloc", "freecad-test:pinned")

_exporter: InMemorySpanExporter | None = None

tracer = trace.get_tracer(__name__)


def _span_to_dict(span: ReadableSpan) -> dict:
    parent_span_id = None
    if span.parent is not None:
        parent_span_id = format(span.parent.span_id, "016x")
    return {
        "name": span.name,
        "start_time_ns": span.start_time,
        "end_time_ns": span.end_time,
        "duration_ms": (span.end_time - span.start_time) / 1_000_000 if span.end_time and span.start_time else None,
        "parent_span_id": parent_span_id,
        "span_id": format(span.context.span_id, "016x"),
        "trace_id": format(span.context.trace_id, "032x"),
        "status": span.status.status_code.name,
        "attributes": dict(span.attributes) if span.attributes else {},
    }


def pytest_configure(config: pytest.Config) -> None:
    global _exporter  # noqa: PLW0603
    _exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    trace.set_tracer_provider(provider)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _exporter is None:
        return
    spans = _exporter.get_finished_spans()
    if not spans:
        return
    dest = undeclared_outputs_dir() / "otel_spans.jsonl"
    with dest.open("w") as f:
        for span in spans:
            f.write(json.dumps(_span_to_dict(span)) + "\n")
    logger.info("Exported %d spans to %s", len(spans), dest)


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
