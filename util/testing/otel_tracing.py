"""OpenTelemetry tracing for test profiling.

Configures a TracerProvider with an in-memory exporter, exporting spans
as JSONL to TEST_UNDECLARED_OUTPUTS_DIR.

Usage in conftest.py:

    from util.testing.otel_tracing import configure_tracing, export_traces

    def pytest_configure(config):
        configure_tracing(config)

    def pytest_sessionfinish(session, exitstatus):
        export_traces(session.config)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

_stash_key = pytest.StashKey[InMemorySpanExporter]()


def configure_tracing(config: pytest.Config) -> None:
    """Set up OTel with in-memory exporter. Call from pytest_configure."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    config.stash[_stash_key] = exporter
    logger.debug("OTel tracing configured with in-memory exporter")


def export_traces(config: pytest.Config, filename: str = "otel_spans.jsonl") -> Path | None:
    """Export collected spans to TEST_UNDECLARED_OUTPUTS_DIR as JSONL. Call from pytest_sessionfinish."""
    exporter = config.stash.get(_stash_key, None)
    if exporter is None:
        return None

    spans = exporter.get_finished_spans()
    if not spans:
        logger.debug("No spans collected, skipping trace export")
        return None

    dest = undeclared_outputs_dir() / filename
    with dest.open("w") as f:
        for span in spans:
            f.write(span.to_json(indent=None) + "\n")
    logger.info("Exported %d spans to %s", len(spans), dest)
    return dest
