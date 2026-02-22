"""OTLP trace exporter for claude_hooks → Grafana Alloy → Tempo.

Configured via `DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT` and
`DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN`; no-ops when absent.
"""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from tools.claude_hooks.settings import HookSettings

logger = logging.getLogger(__name__)


def init(settings: HookSettings) -> None:
    """Initialize the OTLP tracer provider from settings.

    Reads endpoint and bearer token from HookSettings
    (env: DUCKTAPE_CLAUDE_HOOKS_OTEL_ENDPOINT / DUCKTAPE_CLAUDE_HOOKS_OTEL_AUTH_TOKEN).
    No-op if otel_endpoint is not set.
    """
    if not settings.otel_endpoint:
        return

    headers: dict[str, str] = {}
    if settings.otel_auth_token:
        headers["Authorization"] = settings.otel_auth_token

    exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, headers=headers)
    resource = Resource.create({"service.name": "claude-hooks"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info(f"OTEL: traces → {settings.otel_endpoint}")
