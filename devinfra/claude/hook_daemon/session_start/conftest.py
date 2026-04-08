from util.testing.otel_tracing import configure_tracing, export_traces


def pytest_configure(config):
    configure_tracing(config)


def pytest_sessionfinish(session, exitstatus):
    export_traces(session.config)
