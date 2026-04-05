"""OpenTelemetry tracing for test profiling.

Thin shim — re-exports from util.testing.otel_tracing for backwards compat.

Usage:
    # In conftest.py
    from props.testing.otel_tracing import tracing

    def pytest_configure(config):
        tracing.configure()

    def pytest_sessionfinish(session, exitstatus):
        tracing.export_to_file()
"""

from util.testing.otel_tracing import TracingConfig, span_to_dict, tracing

__all__ = ["TracingConfig", "span_to_dict", "tracing"]
