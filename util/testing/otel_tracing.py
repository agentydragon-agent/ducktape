"""OpenTelemetry tracing for test profiling.

Configures a TracerProvider that writes spans to JSONL in
TEST_UNDECLARED_OUTPUTS_DIR immediately as each span ends. Spans are
flushed to disk on completion via SimpleSpanProcessor, so traces survive
even if the test is killed by Bazel timeout (SIGKILL).

Usage in conftest.py:

    from util.testing.otel_tracing import configure_tracing

    def pytest_configure(config):
        configure_tracing(config)
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)


class _StreamingJsonlExporter(SpanExporter):
    """Appends each span as JSONL to a file on disk immediately."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a")

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            self._file.write(span.to_json(indent=None) + "\n")
        self._file.flush()
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self._file.close()


def configure_tracing(config=None, filename: str = "otel_spans.jsonl") -> None:
    """Set up OTel with streaming JSONL exporter. Call from pytest_configure."""
    dest = undeclared_outputs_dir() / filename
    exporter = _StreamingJsonlExporter(dest)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.debug("OTel tracing configured, streaming to %s", dest)
