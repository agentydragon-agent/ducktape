"""OTLP trace exporter for claude → Grafana Alloy → Tempo.

Configured via OtelConfig (from .claude_hooks/config.yaml + env var overrides).
"""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from devinfra.claude.hook_config import OtelConfig

logger = logging.getLogger(__name__)


def init_from_config(config: OtelConfig) -> None:
    """Initialize OTLP tracing. No-op if endpoint is not set."""
    if not config.endpoint:
        return

    headers: dict[str, str] = {}
    if config.auth_token:
        # Authentik proxy expects "Bearer <token>". The auth_token value is
        # the raw Authentik service account key from the k8s secret.
        value = config.auth_token if " " in config.auth_token else f"Bearer {config.auth_token}"
        headers["Authorization"] = value

    exporter = OTLPSpanExporter(endpoint=config.endpoint, headers=headers)
    resource = Resource.create({"service.name": "claude-hooks"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("OTEL: traces → %s", config.endpoint)
