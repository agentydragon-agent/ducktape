"""OpenTelemetry tracing for claude hooks.

Sets up a single TracerProvider with two exporters:
- Local JSONL file (per-session, for post-hoc analysis)
- Remote OTLP/HTTP (Grafana Alloy → Tempo, for live dashboards)

Both are optional — local file needs session_dir, remote needs OtelConfig.
"""

import logging
from pathlib import Path

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor

from devinfra.claude.hook_config import OtelConfig

logger = logging.getLogger(__name__)

# Default flush timeout. 500ms is enough for a healthy local/nearby endpoint.
DEFAULT_FLUSH_TIMEOUT_MS = 500


def _format_span(span: ReadableSpan) -> str:
    """Format a span as compact single-line JSON."""
    json_str: str = span.to_json(indent=None)
    return json_str + "\n"


def init_tracing(session_id: str, session_dir: Path) -> Path:
    """Initialize OTel tracing with a local file exporter.

    Sets the global TracerProvider. Callers get tracers via
    trace.get_tracer(__name__) as usual. Call add_otlp_exporter()
    later to also export to Grafana Alloy. Returns trace_file_path.
    """
    trace_file = session_dir / "traces.jsonl"

    resource = Resource.create({"service.name": "claude-hooks", "session.id": session_id})
    provider = TracerProvider(resource=resource)

    # Local file exporter (always enabled)
    file_exporter = ConsoleSpanExporter(out=trace_file.open("a"), formatter=_format_span)
    provider.add_span_processor(SimpleSpanProcessor(file_exporter))
    logger.info("Tracing: local file → %s", trace_file)

    trace.set_tracer_provider(provider)
    return trace_file


def add_otlp_exporter(config: OtelConfig) -> None:
    """Add remote OTLP/HTTP exporter to the existing TracerProvider.

    No-op if endpoint is not set or no SDK provider is configured.
    """
    if not config.endpoint:
        return

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        return

    headers: dict[str, str] = {}
    if config.bearer_token:
        # Authentik proxy expects "Bearer <token>". The auth_token value is
        # the raw Authentik service account key from the k8s secret.
        value = config.bearer_token if " " in config.bearer_token else f"Bearer {config.bearer_token}"
        headers["Authorization"] = value

    exporter = OTLPSpanExporter(endpoint=config.endpoint, headers=headers)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    logger.info("Tracing: OTLP → %s", config.endpoint)


def flush(timeout_ms: int = DEFAULT_FLUSH_TIMEOUT_MS) -> None:
    """Flush buffered spans. Warns and returns if the endpoint is slow/down."""
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        return
    if not provider.force_flush(timeout_millis=timeout_ms):
        logger.warning("OTEL: flush timed out after %dms — endpoint may be unreachable. Spans may be lost.", timeout_ms)


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider."""
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()
